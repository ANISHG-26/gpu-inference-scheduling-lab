"""Small, bounded same-origin operator for the inference lab."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import copy
import json
import os
from pathlib import Path
import re
import socket
import ssl
import threading
import time
from typing import Any
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

from . import benchmark


NAMESPACE = "inference-lab"
KUBE_URL = "https://kubernetes.default.svc"
KUBE_CA = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
KUBE_TOKEN = "/var/run/secrets/kubernetes.io/serviceaccount/token"
KUBE_TIMEOUT = 3.0
MAX_KUBE_BYTES = 1024 * 1024
MAX_BODY_BYTES = 2048
MAX_WORKERS = 8
EXPERIMENT_TIMEOUT = 65
EXPERIMENT_URL = "http://inference-serve-svc.inference-lab.svc.cluster.local:8000"
STATIC_ROOT = Path(os.environ.get("OPERATOR_STATIC_ROOT", "/app/operator/static"))
STATIC_FILES = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}
LESSON_IDS = {"01-single-node-inference", "02-two-node-inference"}
CONCURRENCY_OPTIONS = {1, 2, 4, 8}
DNS1123_LABEL = re.compile(r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$")
EXPERIMENT_LOCK = threading.Lock()
EXPERIMENT: dict[str, Any] | None = None
EXPERIMENT_RUNNING = False


def _catalog() -> tuple[dict[str, Any], ...]:
    from .lessons import CATALOG
    return CATALOG


def _active_lesson() -> str | None:
    value = os.environ.get("ACTIVE_LESSON")
    return value if value in LESSON_IDS else None


def _expected_ray_cluster() -> str | None:
    value = os.environ.get("EXPECTED_RAY_CLUSTER", "")
    return value if len(value) <= 63 and DNS1123_LABEL.fullmatch(value) else None


def _expiry() -> int | None:
    try:
        value = int(os.environ.get("LAB_EXPIRES_AT", ""))
    except ValueError:
        return None
    return value if value > 0 else None


def _session(now: int | None = None) -> dict[str, Any]:
    now = int(time.time()) if now is None else now
    expires = _expiry()
    if expires is None:
        return {"expires_at": None, "remaining_seconds": None, "status": "unconfigured"}
    remaining = expires - now
    return {"expires_at": expires, "remaining_seconds": max(0, remaining), "status": "active" if remaining > 0 else "expired"}


def _kube_context() -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=KUBE_CA)
    context.check_hostname = True
    return context


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def _list_pods() -> list[dict[str, Any]]:
    token = Path(KUBE_TOKEN).read_text(encoding="utf-8").strip()
    if not token or len(token) > 8192 or "\n" in token:
        raise ValueError("unavailable")
    request = Request(
        f"{KUBE_URL}/api/v1/namespaces/{NAMESPACE}/pods?limit=500",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    opener = build_opener(ProxyHandler({}), _NoRedirect(), HTTPSHandler(context=_kube_context()))
    with opener.open(request, timeout=KUBE_TIMEOUT) as response:
        data = response.read(MAX_KUBE_BYTES + 1)
    if len(data) > MAX_KUBE_BYTES:
        raise ValueError("unavailable")
    payload = json.loads(data)
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list) or len(payload["items"]) > 500:
        raise ValueError("unavailable")
    metadata = payload.get("metadata")
    if isinstance(metadata, dict) and metadata.get("continue"):
        raise ValueError("unavailable")
    return payload["items"]


def _labels(pod: dict[str, Any]) -> dict[str, str]:
    value = (pod.get("metadata") or {}).get("labels")
    return value if isinstance(value, dict) else {}


def _safe_pods(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for pod in items:
        if not isinstance(pod, dict):
            continue
        meta = pod.get("metadata") or {}
        spec, status = pod.get("spec") or {}, pod.get("status") or {}
        labels = _labels(pod)
        if labels.get("app") == "vllm":
            role = "model"
        elif labels.get("ray.io/node-type") == "head":
            role = "Ray head"
        elif labels.get("ray.io/node-type") == "worker":
            role = "Ray worker"
        elif labels.get("app") == "lab-operator":
            role = "operator"
        else:
            continue
        conditions = status.get("conditions") or []
        ready = any(isinstance(c, dict) and c.get("type") == "Ready" and c.get("status") == "True" for c in conditions)
        controller = next((ref for ref in (meta.get("ownerReferences") or []) if isinstance(ref, dict) and ref.get("controller") is True and ref.get("kind") in {"StatefulSet", "RayCluster"}), {})
        result.append({
            "name": _bounded_string(meta.get("name"), 253),
            "uid": _bounded_string(meta.get("uid"), 128),
            "node": _bounded_string(spec.get("nodeName"), 253) or None,
            "role": role,
            "ready": bool(ready),
            "phase": status.get("phase") if status.get("phase") in {"Pending", "Running", "Succeeded", "Failed", "Unknown"} else "Unknown",
            "terminating": bool(meta.get("deletionTimestamp")),
            "owner": controller.get("name"),
            "owner_kind": controller.get("kind"),
            "ray_cluster_label": labels.get("ray.io/cluster"),
            "ray_serve": labels.get("ray.io/serve"),
            "is_ray_node": labels.get("is-ray-node"),
        })
    return result


def _bounded_string(value: Any, maximum: int) -> str:
    return value[:maximum] if isinstance(value, str) else ""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate property")
        result[key] = value
    return result


def _expected_counts(lesson_id: str) -> tuple[int, int, int]:
    if lesson_id == "01-single-node-inference":
        return 1, 1, 1
    if lesson_id == "02-two-node-inference":
        return 2, 1, 2
    return 0, 0, 0


def _placement(lesson_id: str | None, items: list[dict[str, Any]]) -> dict[str, Any]:
    if lesson_id is None:
        return {"valid": False, "reason": "No active lesson is configured."}
    model_candidates = [p for p in items if p["role"] == "model"]
    head_candidates = [p for p in items if p["role"] == "Ray head"]
    worker_candidates = [p for p in items if p["role"] == "Ray worker"]
    model_n, head_n, worker_n = _expected_counts(lesson_id)
    live_models = [p for p in model_candidates if not p["terminating"]]
    ready_models = [p for p in live_models if p["ready"] and p["phase"] == "Running"]
    if len(live_models) != model_n or len(ready_models) != model_n:
        return {"valid": False, "reason": f"Waiting for {model_n} Ready model pod(s) owned by StatefulSet vllm."}
    if any(p["owner_kind"] != "StatefulSet" or p["owner"] != "vllm" for p in live_models):
        return {"valid": False, "reason": "Model pods must be controlled by StatefulSet vllm."}
    expected_names = {f"vllm-{i}" for i in range(model_n)}
    if {p["name"] for p in ready_models} != expected_names:
        return {"valid": False, "reason": "Model pod identities do not match the active lesson."}
    model_nodes = [p["node"] for p in ready_models]
    if any(not node for node in model_nodes) or (model_n > 1 and len(set(model_nodes)) != model_n):
        return {"valid": False, "reason": "Model pods must be scheduled on distinct nodes."}
    ray_heads = [p for p in head_candidates if not p["terminating"]]
    live_workers = [p for p in worker_candidates if not p["terminating"]]
    expected_cluster = _expected_ray_cluster()
    if expected_cluster is None:
        return {"valid": False, "reason": "Expected Ray cluster binding is unavailable."}
    if any(
        p["owner_kind"] != "RayCluster"
        or p["owner"] != expected_cluster
        or p["ray_cluster_label"] != expected_cluster
        or p["ray_serve"] != "true"
        or p["is_ray_node"] != "yes"
        for p in ray_heads + live_workers
    ):
        return {"valid": False, "reason": "Ray pod ownership and serving labels do not match the configured cluster."}
    cluster_names = {p["owner"] for p in ray_heads + live_workers}
    if cluster_names != {expected_cluster} or len(ray_heads) != head_n:
        return {"valid": False, "reason": "Waiting for one active RayCluster with exactly one head."}
    cluster = expected_cluster
    ray_workers = [p for p in live_workers if p["owner"] == cluster]
    ready = [p for p in ray_heads + ray_workers if p["owner"] == cluster and p["ready"] and p["phase"] == "Running"]
    if len(ray_workers) != worker_n or len(ready) != 1 + worker_n:
        return {"valid": False, "reason": f"Waiting for one Ready Ray head and {worker_n} Ready worker(s)."}
    topology = ready_models + [p for p in ready if p["owner"] == cluster]
    nodes = [p["node"] for p in topology]
    if any(not node for node in nodes) or len(set(nodes)) != (1 if lesson_id == "01-single-node-inference" else 2):
        return {"valid": False, "reason": "Model and Ray pods must occupy the lesson's required one or two nodes."}
    if worker_n > 1 and len({p["node"] for p in ray_workers}) != worker_n:
        return {"valid": False, "reason": "Ray workers must be scheduled on distinct nodes."}
    return {"valid": True, "reason": "Model pods and the single RayCluster are Ready on the required nodes.", "ray_cluster": cluster, "model_nodes": model_nodes}


def _serving_uids(lesson_id: str, pods: list[dict[str, Any]]) -> set[str]:
    selected = [p for p in pods if not p["terminating"] and p["role"] in {"model", "Ray head", "Ray worker"}]
    uids = {p["uid"] for p in selected if p["uid"]}
    return uids if len(uids) == len(selected) else set()


def _snapshot() -> dict[str, Any]:
    now = int(time.time())
    lesson_id = _active_lesson()
    try:
        items = _safe_pods(_list_pods())
        return {"status": "ok", "observed_at": now, "pods": items, "placement": _placement(lesson_id, items)}
    except Exception:
        return {"status": "unavailable", "observed_at": now, "pods": [], "placement": {"valid": False, "reason": "Kubernetes pod status is temporarily unavailable."}}


def state() -> dict[str, Any]:
    global EXPERIMENT
    now = int(time.time())
    observation = _snapshot()
    lesson_id = _active_lesson()
    session = _session(now)
    with EXPERIMENT_LOCK:
        experiment = copy.deepcopy(EXPERIMENT)
        experiment_running = EXPERIMENT_RUNNING
    lessons = []
    for lesson in _catalog():
        item = dict(lesson)
        item["state"] = "prepared"
        item["reason"] = "Lesson is prepared; no live evidence is available."
        current_ready = observation["status"] == "ok" and observation["placement"]["valid"]
        item["actions_enabled"] = bool(
            os.environ.get("LAB_ACTIONS_ENABLED", "false").lower() == "true"
            and lesson.get("id") == lesson_id
            and lesson.get("gate") is None
            and session["status"] == "active"
            and current_ready
            and not experiment_running
        )
        if lesson.get("id") == lesson_id:
            if current_ready and session["status"] == "active":
                item["state"] = "deployed"
                item["reason"] = observation["placement"]["reason"]
            if experiment and experiment.get("lesson_id") == lesson_id and experiment.get("state") == "measured":
                current = _serving_uids(lesson_id, observation["pods"])
                if session["status"] != "active":
                    stale_reason = "session_expired"
                    reason_text = "The session expired after the experiment."
                elif observation["status"] != "ok":
                    stale_reason = "observation_unavailable"
                    reason_text = "Current Kubernetes status is unavailable."
                elif not current_ready:
                    stale_reason = "placement_unready"
                    reason_text = "The lesson placement is no longer Ready."
                elif current != experiment.get("pod_uids"):
                    stale_reason = "pod_identity_changed"
                    reason_text = "Pod identities changed after the experiment."
                else:
                    stale_reason = None
                    reason_text = "Experiment completed against the current pod identities."
                if stale_reason is None:
                    item["state"] = "measured"
                    item["reason"] = reason_text
                else:
                    experiment["state"] = "failed"
                    experiment["error"] = stale_reason
                    item["state"] = "failed"
                    item["reason"] = reason_text
                    with EXPERIMENT_LOCK:
                        if EXPERIMENT is not None and EXPERIMENT.get("id") == experiment.get("id"):
                            EXPERIMENT["state"] = "failed"
                            EXPERIMENT["error"] = stale_reason
            if observation["status"] == "ok" and any(
                p["role"] in {"model", "Ray head", "Ray worker"} and p["phase"] == "Failed" and not p["terminating"]
                for p in observation["pods"]
            ):
                item["state"] = "failed"
                item["reason"] = "A required pod is in Failed state."
            if experiment and experiment.get("lesson_id") == lesson_id and experiment.get("state") == "failed":
                failure_reasons = {
                    "pod_identity_changed": "Pod identities changed after the experiment.",
                    "placement_unready": "The lesson placement is no longer Ready.",
                    "observation_unavailable": "Current Kubernetes status is unavailable.",
                    "session_expired": "The session expired during or after the experiment.",
                    "requests_failed": "One or more benchmark requests failed.",
                    "inference_evidence_missing": "The experiment returned no valid completion token evidence.",
                    "experiment_unavailable": "The experiment could not be completed.",
                }
                item["state"] = "failed"
                item["reason"] = failure_reasons.get(experiment.get("error"), "The experiment failed.")
        lessons.append(item)
    return {"server_time": now, "session": session, "active_lesson": lesson_id, "observation": _public_observation(observation), "lessons": lessons, "experiment": _public_experiment(experiment)}


def _public_experiment(experiment: dict[str, Any] | None) -> dict[str, Any] | None:
    if experiment is None:
        return None
    return {k: v for k, v in experiment.items() if k not in {"pod_uids", "future"}}


def _public_observation(observation: dict[str, Any]) -> dict[str, Any]:
    return {
        **observation,
        "pods": [{key: pod[key] for key in ("name", "uid", "node", "role", "ready", "phase")} | {"terminating": pod["terminating"]} for pod in observation["pods"]],
    }


def _has_inference_evidence(metrics: list[dict[str, Any]]) -> bool:
    return len(metrics) == 8 and all(
        metric.get("completed") is True
        and type(metric.get("completion_tokens")) is int
        and metric["completion_tokens"] > 0
        for metric in metrics
    )


def _run_experiment(experiment_id: str, lesson_id: str, concurrency: int, before: set[str]) -> None:
    global EXPERIMENT, EXPERIMENT_RUNNING
    started = int(time.time())
    metrics: list[dict[str, Any]] = []
    wall_started = time.perf_counter()
    summary: dict[str, Any] | None = None
    try:
        total = 8
        remaining = total
        index = 1
        while remaining:
            if _session()["status"] != "active":
                raise RuntimeError("session_expired")
            count = min(remaining, concurrency)
            report = benchmark.run_benchmark(EXPERIMENT_URL, requests=count, concurrency=concurrency, max_tokens=32, timeout=EXPERIMENT_TIMEOUT)
            for metric in report.get("requests", []):
                metric["request"] = index
                index += 1
                metrics.append(metric)
            remaining -= count
        summary = benchmark.summarize(metrics, time.perf_counter() - wall_started)
        after = _snapshot()
        after_ids = _serving_uids(lesson_id, after["pods"]) if after["status"] == "ok" else set()
        if _session()["status"] != "active":
            error = "session_expired"
        elif after["status"] != "ok":
            error = "observation_unavailable"
        elif not after["placement"]["valid"]:
            error = "placement_unready"
        elif not before or before != after_ids:
            error = "pod_identity_changed"
        elif summary.get("completed") != total:
            error = "requests_failed"
        elif not _has_inference_evidence(metrics):
            error = "inference_evidence_missing"
        else:
            error = None
        result = {"id": experiment_id, "lesson_id": lesson_id, "state": "measured" if error is None else "failed", "concurrency": concurrency, "started_at": started, "finished_at": int(time.time()), "summary": summary, "error": error, "identity_note": "Topology pod UIDs matched before and after; per-request model identity is unknown for balanced inference." if after["status"] == "ok" and before == after_ids else "Pod identity could not be verified.", "pod_uids": before}
    except Exception as exc:
        reason = str(exc) if str(exc) == "session_expired" else "experiment_unavailable"
        if metrics:
            summary = benchmark.summarize(metrics, time.perf_counter() - wall_started)
        result = {"id": experiment_id, "lesson_id": lesson_id, "state": "failed", "concurrency": concurrency, "started_at": started, "finished_at": int(time.time()), "summary": summary, "error": reason, "identity_note": "Pod identity could not be verified.", "pod_uids": before}
    finally:
        with EXPERIMENT_LOCK:
            EXPERIMENT = result
            EXPERIMENT_RUNNING = False


def _loopback_host(host_header: str) -> bool:
    if not isinstance(host_header, str) or len(host_header) > 300:
        return False
    try:
        parsed = urlsplit("http://" + host_header)
        port = parsed.port
        if parsed.path or parsed.username or parsed.password or not parsed.hostname or port is None:
            return False
        if str(port) != parsed.netloc.rsplit(":", 1)[-1].rstrip("]"):
            return False
        host = parsed.hostname.lower()
        if host == "localhost":
            return True
        import ipaddress
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class _BoundedServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 16

    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler]):
        self.admission = threading.BoundedSemaphore(MAX_WORKERS)
        super().__init__(address, handler)

    def process_request(self, request: socket.socket, client_address: Any) -> None:
        if not self.admission.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
            except OSError:
                pass
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.admission.release()
            raise

    def process_request_thread(self, request: socket.socket, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.admission.release()


class OperatorHandler(BaseHTTPRequestHandler):
    server_version = "InferenceLabOperator/1"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(3.0)

    def _host_ok(self) -> bool:
        hosts = self.headers.get_all("Host", [])
        return len(hosts) == 1 and _loopback_host(hosts[0])

    def _send(self, code: int, value: Any, content_type: str = "application/json; charset=utf-8") -> None:
        self.close_connection = True
        body = value if isinstance(value, bytes) else json.dumps(value, separators=(",", ":")).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            self._send(200, b"ok", "text/plain; charset=utf-8")
            return
        if not self._host_ok():
            self._send(421, {"error": "invalid_host"})
            return
        if self.path == "/api/state":
            self._send(200, state())
        elif self.path in STATIC_FILES:
            try:
                body = (STATIC_ROOT / STATIC_FILES[self.path]).read_bytes()
            except OSError:
                self._send(404, {"error": "not_found"})
                return
            mime = "text/html; charset=utf-8" if self.path == "/" else "text/javascript; charset=utf-8" if self.path.endswith(".js") else "text/css; charset=utf-8"
            self._send(200, body, mime)
        else:
            self._send(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._host_ok():
            self._send(421, {"error": "invalid_host"})
            return
        if any(len(self.headers.get_all(name, [])) != 1 for name in ("Origin", "Content-Length")):
            self._send(400, {"error": "invalid_request"})
            return
        if self.path != "/api/experiments":
            self._send(404, {"error": "not_found"})
            return
        origin = self.headers.get("Origin")
        if origin != f"http://{self.headers.get('Host', '')}" or self.headers.get("Content-Type", "").lower() != "application/json":
            self._send(403, {"error": "same_origin_required"})
            return
        if self.headers.get("Transfer-Encoding") or self.headers.get("Expect"):
            self._send(400, {"error": "invalid_request"})
            return
        try:
            length_text = self.headers.get("Content-Length", "")
            if not length_text.isascii() or not length_text.isdigit():
                raise ValueError
            length = int(length_text)
        except ValueError:
            self._send(400, {"error": "invalid_request"})
            return
        if not 0 < length <= MAX_BODY_BYTES:
            self._send(413, {"error": "invalid_request_size"})
            return
        try:
            payload = json.loads(self.rfile.read(length), object_pairs_hook=_unique_object)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            self._send(400, {"error": "invalid_json"})
            return
        if not isinstance(payload, dict) or set(payload) != {"lesson_id", "concurrency"}:
            self._send(400, {"error": "invalid_request"})
            return
        lesson_id, concurrency = payload["lesson_id"], payload["concurrency"]
        if (not isinstance(lesson_id, str) or lesson_id not in LESSON_IDS
                or isinstance(concurrency, bool) or not isinstance(concurrency, int)
                or concurrency not in CONCURRENCY_OPTIONS):
            self._send(400, {"error": "invalid_request"})
            return
        if os.environ.get("LAB_ACTIONS_ENABLED", "false").lower() != "true":
            self._send(403, {"error": "actions_disabled"})
            return
        session = _session()
        if _active_lesson() != lesson_id or session["status"] != "active":
            self._send(503, {"error": "lesson_unavailable"})
            return
        remaining_required = ((8 + concurrency - 1) // concurrency) * (EXPERIMENT_TIMEOUT + 0) + 30
        if (session["remaining_seconds"] or 0) < remaining_required:
            self._send(503, {"error": "insufficient_session_time"})
            return
        observation = _snapshot()
        if observation["status"] != "ok" or not observation["placement"]["valid"]:
            self._send(503, {"error": "lesson_not_ready"})
            return
        pods = observation["pods"]
        uids = _serving_uids(lesson_id, pods)
        if not uids:
            self._send(503, {"error": "model_identity_unavailable"})
            return
        global EXPERIMENT, EXPERIMENT_RUNNING
        with EXPERIMENT_LOCK:
            if EXPERIMENT_RUNNING:
                self._send(409, {"error": "experiment_running"})
                return
            experiment_id = f"experiment-{int(time.time())}-{threading.get_ident()}"
            experiment = {"id": experiment_id, "lesson_id": lesson_id, "state": "running", "concurrency": concurrency, "started_at": int(time.time()), "finished_at": None, "summary": None, "error": None, "identity_note": "Kubernetes serving workload pod UIDs captured before the experiment.", "pod_uids": uids}
            EXPERIMENT = experiment
            EXPERIMENT_RUNNING = True
        threading.Thread(target=_run_experiment, args=(experiment_id, lesson_id, concurrency, uids), daemon=True).start()
        self._send(202, _public_experiment(experiment))

    def log_message(self, *_args: Any) -> None:
        return


def serve() -> None:
    server = _BoundedServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), OperatorHandler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    serve()
