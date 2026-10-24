"""Fixed, bounded HTTP adapter for the lab's Triton CPU teaching model.

This module reports observations only. It does not claim runtime or deployment
acceptance; that requires the real Triton service to pass the same protocol.
"""

from __future__ import annotations

import json
import math
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Any

from .bounded_http import request

TRITON_BASE = "http://triton.inference-lab.svc.cluster.local:8000"
MODEL = "lab_double"
VERSION = "1"
_ALLOWED = (1, 2, 4, 8)
_MAX_COUNTER = 2**63
_OUTPUT_LIMIT = 65536
_INPUTS = tuple(tuple(float(i * 4 + j + 1) for j in range(4)) for i in range(8))


def _enum(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value not in _ALLOWED:
        raise ValueError(f"{name} must be one of 1, 2, 4, or 8")
    return value


def required_seconds(concurrency: int, batch_size: int) -> int:
    """Conservative wall-clock budget including protocol probes and margin."""
    concurrency = _enum(concurrency, "concurrency")
    batch_size = _enum(batch_size, "batch_size")
    requests = 8 // batch_size
    waves = math.ceil(requests / concurrency)
    # Inference waves (10s each), three four-GET snapshots (3s each), two
    # negative probes (10s each), plus scheduling/cleanup margin.
    return waves * 10 + 80


def _json_response(status: int, body: bytes) -> Any:
    if not isinstance(body, bytes) or len(body) > _OUTPUT_LIMIT:
        raise ValueError("response body exceeded the protocol limit")
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("response was not valid JSON") from exc


def _get(path: str, timeout: int = 3) -> tuple[int, Any]:
    status, body = request("GET", TRITON_BASE + path, timeout=timeout, max_bytes=_OUTPUT_LIMIT)
    return status, _json_response(status, body)


def _counter(value: Any) -> int:
    if isinstance(value, str):
        if not value.isdecimal() or (len(value) > 1 and value.startswith("0")):
            raise ValueError("stats contained an invalid counter")
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < _MAX_COUNTER:
        raise ValueError("stats contained an invalid counter")
    return value


def _stats(payload: Any) -> dict[str, int]:
    rows = payload.get("model_stats") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError("stats did not contain exactly the configured model")
    row = rows[0]
    if row.get("name") != MODEL or row.get("version") != VERSION:
        raise ValueError("stats model identity did not match")
    groups = row.get("inference_stats")
    success = groups.get("success") if isinstance(groups, dict) else None
    if not isinstance(success, dict):
        raise ValueError("stats success counter was missing")
    return {
        "success": _counter(success.get("count")),
        "inference_count": _counter(row.get("inference_count")),
        "execution_count": _counter(row.get("execution_count")),
    }


def _observe() -> dict[str, Any]:
    ready_status, _ = request("GET", TRITON_BASE + f"/v2/models/{MODEL}/versions/{VERSION}/ready", timeout=3, max_bytes=_OUTPUT_LIMIT)
    metadata_status, metadata = _get(f"/v2/models/{MODEL}/versions/{VERSION}")
    identity = None
    if isinstance(metadata, dict) and metadata.get("name") == MODEL and metadata.get("versions") == [VERSION]:
        inputs, outputs = metadata.get("inputs"), metadata.get("outputs")
        if isinstance(inputs, list) and isinstance(outputs, list) and len(inputs) == 1 and len(outputs) == 1:
            inp, out = inputs[0], outputs[0]
            if (isinstance(inp, dict) and inp.get("name") == "INPUT" and inp.get("datatype") == "FP32" and inp.get("shape") == [-1, 4]
                    and isinstance(out, dict) and out.get("name") == "OUTPUT" and out.get("datatype") == "FP32" and out.get("shape") == [-1, 4]):
                identity = {"name": MODEL, "version": VERSION}
    stats_status, stats_payload = _get(f"/v2/models/{MODEL}/versions/{VERSION}/stats")
    # Fetch config only to verify the configured model identity; expose no raw
    # provider response or configuration fields to callers.
    config_status, config_payload = _get(f"/v2/models/{MODEL}/versions/{VERSION}/config")
    config_ok = isinstance(config_payload, dict) and config_payload.get("name") == MODEL
    result: dict[str, Any] = {
        "loaded": ready_status == 200 and metadata_status == 200 and identity is not None,
        "ready": ready_status == 200 and metadata_status == 200 and identity is not None and config_status == 200 and config_ok,
        "model": identity,
        "stats": None,
    }
    if stats_status == 200:
        try:
            result["stats"] = _stats(stats_payload)
        except ValueError:
            pass
    return result


def observe() -> dict[str, Any]:
    """Return bounded, sanitized model readiness and supported stats."""
    try:
        return _observe()
    except Exception:
        return {"loaded": False, "ready": False, "model": None, "stats": None}


def _infer(items: tuple[tuple[float, ...], ...]) -> tuple[float, bool]:
    body = {"inputs": [{"name": "INPUT", "datatype": "FP32", "shape": [len(items), 4], "data": [x for row in items for x in row]}]}
    started = time.perf_counter()
    status, raw = request(
        "POST", TRITON_BASE + f"/v2/models/{MODEL}/versions/{VERSION}/infer",
        json_body=body, timeout=10, max_bytes=_OUTPUT_LIMIT,
    )
    elapsed = time.perf_counter() - started
    if status != 200:
        return elapsed, False
    payload = _json_response(status, raw)
    outputs = payload.get("outputs") if isinstance(payload, dict) else None
    if not isinstance(outputs, list) or len(outputs) != 1 or not isinstance(outputs[0], dict):
        return elapsed, False
    output = outputs[0]
    expected = [x * 2 for row in items for x in row]
    shape = output.get("shape")
    data = output.get("data")
    if (payload.get("model_name") != MODEL or payload.get("model_version") != VERSION
            or not isinstance(shape, list) or len(shape) != 2
            or any(type(dimension) is not int for dimension in shape)
            or shape != [len(items), 4]
            or not isinstance(data, list) or len(data) != len(expected)):
        return elapsed, False
    for value in data:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return elapsed, False
        try:
            if not math.isfinite(value):
                return elapsed, False
        except (OverflowError, TypeError):
            return elapsed, False
    return elapsed, (
        output.get("name") == "OUTPUT"
        and output.get("datatype") == "FP32"
        and data == expected
    )


def _probe(path: str, body: dict[str, Any], expected: int) -> int | None:
    try:
        status, raw = request("POST", TRITON_BASE + path, json_body=body, timeout=10, max_bytes=_OUTPUT_LIMIT)
        # The transport intentionally discards error bodies. Preserve only the
        # status code for these fixed probes and never expose response text.
        if 200 <= status < 300:
            _json_response(status, raw)
        return status
    except Exception:
        return None


def run_experiment(concurrency: int, batch_size: int, session_active: Callable[[], bool]) -> dict[str, Any]:
    """Run eight fixed FP32 inputs in bounded waves against the fixed model."""
    try:
        concurrency = _enum(concurrency, "concurrency")
        batch_size = _enum(batch_size, "batch_size")
    except ValueError as exc:
        return {"summary": {}, "triton": {}, "error": str(exc)}

    summary: dict[str, Any] = {
        "requested_inputs": 8, "completed": 0, "errors": 0,
        "requests_completed": 0, "request_errors": 0,
        "p50_ms": None, "p95_ms": None, "batch_mean_ms": None, "wall_seconds": None,
        "inferences_per_second": None,
    }
    triton: dict[str, Any] = {"model": {"name": MODEL, "version": VERSION}, "negative_probes": {}}
    error: str | None = None
    start = time.perf_counter()
    try:
        if not session_active():
            raise ValueError("session expired")
        initial = _observe()
        triton["before"] = initial
        if not initial["ready"] or initial["stats"] is None:
            raise ValueError("Triton model is not ready with valid stats")
        before = initial["stats"]

        groups = [_INPUTS[i:i + batch_size] for i in range(0, 8, batch_size)]
        inference_start = time.perf_counter()
        latencies: list[float] = []
        for offset in range(0, len(groups), concurrency):
            if not session_active():
                raise ValueError("session expired")
            wave = groups[offset:offset + concurrency]
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                future_groups = {pool.submit(_infer, group): group for group in wave}
                for future in as_completed(future_groups):
                    try:
                        elapsed, valid = future.result()
                    except Exception:
                        summary["errors"] += len(future_groups[future])
                        summary["request_errors"] += 1
                        continue
                    latencies.append(elapsed)
                    if valid:
                        summary["completed"] += len(future_groups[future])
                        summary["requests_completed"] += 1
                    else:
                        summary["errors"] += len(future_groups[future])
                        summary["request_errors"] += 1
            if not session_active():
                raise ValueError("session expired")

        summary["wall_seconds"] = time.perf_counter() - inference_start
        summary["p50_ms"] = round(statistics.median(latencies) * 1000, 3) if latencies else None
        summary["p95_ms"] = round(sorted(latencies)[math.ceil(len(latencies) * .95) - 1] * 1000, 3) if latencies else None
        summary["batch_mean_ms"] = round(statistics.mean(latencies) * 1000, 3) if latencies else None
        summary["inferences_per_second"] = round(summary["completed"] / summary["wall_seconds"], 3) if summary["wall_seconds"] and summary["completed"] else None

        # Snapshot valid inference counters before probes, so their possible
        # accounting behavior does not contaminate the inference experiment.
        mid = _observe()
        triton["after_inference"] = mid
        if not mid["ready"] or mid["stats"] is None:
            raise ValueError("Triton readiness or stats recheck failed")
        delta = {key: mid["stats"][key] - before[key] for key in before}
        triton["counter_deltas"] = delta
        if (any(value < 0 for value in delta.values()) or delta["success"] != len(groups)
                or delta["inference_count"] != summary["completed"]
                or not 0 < delta["execution_count"] <= delta["inference_count"]):
            error = "metrics_unverified: Triton counter deltas did not match completed inputs"

        if not session_active():
            raise ValueError("session expired")
        invalid = {"inputs": [{"name": "INPUT", "datatype": "FP32", "shape": [1, 3], "data": [1, 2, 3]}]}
        valid = {"inputs": [{"name": "INPUT", "datatype": "FP32", "shape": [1, 4], "data": [1, 2, 3, 4]}]}
        if not session_active():
            raise ValueError("session expired")
        triton["negative_probes"]["invalid_shape_status"] = _probe(f"/v2/models/{MODEL}/versions/{VERSION}/infer", invalid, 400)
        if not session_active():
            raise ValueError("session expired")
        triton["negative_probes"]["missing_version_status"] = _probe(f"/v2/models/{MODEL}/versions/2/infer", valid, 404)
        if triton["negative_probes"]["invalid_shape_status"] != 400 or triton["negative_probes"]["missing_version_status"] != 404:
            error = error or "negative protocol probe returned an unexpected status"
        if not session_active():
            raise ValueError("session expired")
        final = _observe()
        triton["after_probes"] = final
        if not final["ready"]:
            raise ValueError("Triton readiness recheck failed after negative probes")
        if summary["completed"] != 8 or summary["errors"]:
            error = error or "one or more inference requests failed validation"
    except Exception as exc:
        message = str(exc)
        safe_messages = {
            "session expired", "Triton model is not ready with valid stats",
            "Triton readiness or stats recheck failed",
            "Triton readiness recheck failed after negative probes",
            "one or more inference requests failed validation",
            "response body exceeded the protocol limit", "response was not valid JSON",
        }
        error = error or (message if message in safe_messages else "Triton protocol request failed")
        if summary["wall_seconds"] is None:
            summary["wall_seconds"] = time.perf_counter() - start
    return {"summary": summary, "triton": triton, "error": error}
