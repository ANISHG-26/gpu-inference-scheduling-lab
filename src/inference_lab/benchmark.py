"""Bounded, dependency-free load benchmark for an OpenAI-compatible endpoint."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
from pathlib import Path
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from inference_lab.bounded_http import request as bounded_request


MODEL_ID = "Qwen/Qwen3-0.6B"
PROMPT = "Reply with one short greeting."
MAX_RESPONSE_BYTES = 65536


def validate_url(url: str) -> str:
    """Validate and normalize an endpoint base URL without accepting secrets."""
    if not isinstance(url, str) or not url or any(char.isspace() for char in url):
        raise ValueError("url must be an absolute http(s) URL")
    try:
        parsed = urlsplit(url)
        # Accessing port also validates malformed port values.
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("url must be a valid absolute http(s) URL") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("url must be an absolute http(s) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("url must not contain credentials")
    if "?" in url or "#" in url:
        raise ValueError("url must not contain a query or fragment")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _validate_integer(name: str, value: int, minimum: int, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer from {minimum} to {maximum}")


def _valid_token_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _request_once(index: int, endpoint: str, max_tokens: int, timeout: float) -> dict[str, Any]:
    started = time.perf_counter()
    status = None
    error = None
    prompt_tokens = None
    completion_tokens = None
    completed = False
    try:
        status, response_body = bounded_request(
            "POST",
            endpoint,
            json_body={
                "model": MODEL_ID,
                "messages": [{"role": "user", "content": PROMPT}],
                "max_tokens": max_tokens,
                "stream": False,
            },
            timeout=timeout,
            max_bytes=MAX_RESPONSE_BYTES,
        )
        if 200 <= status < 300:
            try:
                decoded = json.loads(response_body) if len(response_body) <= MAX_RESPONSE_BYTES else None
            except (UnicodeDecodeError, json.JSONDecodeError):
                decoded = None
            choices = decoded.get("choices") if isinstance(decoded, dict) else None
            valid_completion = (
                isinstance(choices, list)
                and bool(choices)
                and isinstance(choices[0], dict)
                and isinstance(choices[0].get("message"), dict)
            )
            if not valid_completion:
                error = "invalid_response"
            else:
                completed = True
                usage = decoded.get("usage")
                if isinstance(usage, dict):
                    prompt_value = usage.get("prompt_tokens")
                    completion_value = usage.get("completion_tokens")
                    if _valid_token_count(prompt_value):
                        prompt_tokens = prompt_value
                    if _valid_token_count(completion_value):
                        completion_tokens = completion_value
        else:
            error = "http_error"
    except TimeoutError:
        error = "timeout"
    except (OSError, ValueError):
        error = "connection_error"

    metric = {
        "request": index,
        "status": status,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "completed": completed,
    }
    if prompt_tokens is not None:
        metric["prompt_tokens"] = prompt_tokens
    if completion_tokens is not None:
        metric["completion_tokens"] = completion_tokens
    if error is not None:
        metric["error"] = error
    return metric


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def summarize(request_metrics: list[dict[str, Any]], wall_time_seconds: float) -> dict[str, Any]:
    successful = [metric for metric in request_metrics if metric.get("completed") is True]
    latencies = [metric["elapsed_seconds"] for metric in successful]
    token_counts = [
        metric["completion_tokens"]
        for metric in successful
        if _valid_token_count(metric.get("completion_tokens"))
    ]
    total_tokens = sum(token_counts)
    throughput = total_tokens / wall_time_seconds if wall_time_seconds > 0 and token_counts else None
    return {
        "completed": len(successful),
        "errors": len(request_metrics) - len(successful),
        "p50_latency_seconds": _percentile(latencies, 0.50),
        "p95_latency_seconds": _percentile(latencies, 0.95),
        "completion_tokens_per_second": round(throughput, 6) if throughput is not None else None,
        "wall_time_seconds": round(wall_time_seconds, 6),
    }


def run_benchmark(
    url: str,
    *,
    requests: int = 10,
    concurrency: int = 1,
    max_tokens: int = 32,
    timeout: float = 60,
) -> dict[str, Any]:
    """Send a bounded number of independent, non-streaming requests."""
    endpoint_base = validate_url(url)
    _validate_integer("requests", requests, 1, 100)
    _validate_integer("concurrency", concurrency, 1, 8)
    _validate_integer("max_tokens", max_tokens, 1, 128)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 70:
        raise ValueError("timeout must be greater than 0 and at most 70 seconds")
    endpoint = endpoint_base + "/v1/chat/completions"

    started = time.perf_counter()
    metrics = []
    with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="inference-benchmark") as executor:
        futures = [executor.submit(_request_once, index, endpoint, max_tokens, float(timeout))
                   for index in range(1, requests + 1)]
        for future in as_completed(futures):
            metrics.append(future.result())
    wall_time = time.perf_counter() - started
    metrics.sort(key=lambda metric: metric["request"])
    return {"summary": summarize(metrics, wall_time), "requests": metrics}


def write_report(path: str | Path, report: dict[str, Any]) -> None:
    """Create a metrics report without replacing a pre-existing file."""
    with Path(path).open("x", encoding="utf-8", newline="\n") as output:
        json.dump(report, output, indent=2, sort_keys=True)
        output.write("\n")


def _bounded_int(minimum: int, maximum: int):
    def parse(value: str) -> int:
        try:
            parsed = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"must be an integer from {minimum} to {maximum}") from exc
        if not minimum <= parsed <= maximum:
            raise argparse.ArgumentTypeError(f"must be an integer from {minimum} to {maximum}")
        return parsed

    return parse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark a non-streaming OpenAI-compatible inference endpoint")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="endpoint base URL")
    parser.add_argument("--requests", type=_bounded_int(1, 100), default=10)
    parser.add_argument("--concurrency", type=_bounded_int(1, 8), default=1)
    parser.add_argument("--max-tokens", type=_bounded_int(1, 128), default=32)
    parser.add_argument("--timeout", type=_bounded_int(1, 70), default=60, help="per-request timeout in seconds")
    parser.add_argument("--output", help="create a JSON metrics report at this path (must not already exist)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        report = run_benchmark(
            args.url,
            requests=args.requests,
            concurrency=args.concurrency,
            max_tokens=args.max_tokens,
            timeout=args.timeout,
        )
        if args.output:
            write_report(args.output, report)
        else:
            print(json.dumps(report, indent=2, sort_keys=True))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
