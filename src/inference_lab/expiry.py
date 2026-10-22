"""Authenticated Cloud Run expiry endpoint for one owned GKE cluster."""

from __future__ import annotations

import json
import os
import re
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable, Mapping
from urllib.parse import quote


RUN_ID_RE = re.compile(r"^[0-9a-f]{12}$")
MAX_BODY_BYTES = 16 * 1024
NOT_FOUND_GRACE_SECONDS = 30 * 60


class ExpiryError(ValueError):
    pass


def validate_payload(payload: Any, configured_project: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ExpiryError("payload must be an object")
    required = ("project_id", "zone", "run_id", "cluster_name", "expires_at")
    if any(key not in payload for key in required):
        raise ExpiryError("payload is missing required fields")
    project_id, zone, run_id = payload["project_id"], payload["zone"], payload["run_id"]
    expires_at = payload["expires_at"]
    if not isinstance(project_id, str) or not project_id or project_id != configured_project:
        raise ExpiryError("project does not match service configuration")
    if not isinstance(zone, str) or not zone or "/" in zone:
        raise ExpiryError("invalid zone")
    if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
        raise ExpiryError("invalid run id")
    if payload["cluster_name"] != f"inference-lab-{run_id}":
        raise ExpiryError("cluster name does not match run id")
    if type(expires_at) is not int or expires_at <= 0:
        raise ExpiryError("expires_at must be a positive Unix timestamp")
    return {key: payload[key] for key in required}


def cluster_url(payload: Mapping[str, Any]) -> str:
    return (
        "https://container.googleapis.com/v1/projects/"
        f"{quote(str(payload['project_id']), safe='')}/locations/"
        f"{quote(str(payload['zone']), safe='')}/clusters/"
        f"{quote(str(payload['cluster_name']), safe='')}"
    )


def expected_labels(payload: Mapping[str, Any]) -> dict[str, str]:
    return {
        "managed-by": "inference-lab",
        "lab-run": str(payload["run_id"]),
        "lab-expiry": str(payload["expires_at"]),
    }


def _has_ownership_labels(labels: Any, payload: Mapping[str, Any]) -> bool:
    expected = expected_labels(payload)
    return isinstance(labels, dict) and all(labels.get(key) == value for key, value in expected.items())


def process_expiry(payload: Any, configured_project: str, session: Any,
                   now: Callable[[], float] = time.time) -> tuple[int, str]:
    """Return HTTP status/body; 503 asks Cloud Tasks to retry safely."""
    try:
        request = validate_payload(payload, configured_project)
    except ExpiryError:
        return 400, "invalid expiry request"
    current = int(now())
    if current < request["expires_at"]:
        return 503, "session has not expired"
    try:
        response = session.get(cluster_url(request), timeout=20)
    except Exception:
        return 503, "cluster lookup failed"
    if response.status_code == 404:
        if current < request["expires_at"] + NOT_FOUND_GRACE_SECONDS:
            return 503, "cluster is not visible yet"
        return 200, "cluster absent after expiry grace period"
    if response.status_code != 200:
        return 503, "cluster lookup is temporarily unavailable"
    try:
        cluster = response.json()
    except Exception:
        return 503, "cluster lookup returned invalid data"
    labels = cluster.get("resourceLabels") if isinstance(cluster, dict) else None
    if not _has_ownership_labels(labels, request):
        return 403, "cluster ownership labels do not match"
    try:
        deleted = session.delete(cluster_url(request), timeout=20)
    except Exception:
        return 503, "cluster delete request failed"
    if deleted.status_code == 404:
        # Confirm absence with a fresh GET rather than trusting a racing DELETE.
        try:
            check = session.get(cluster_url(request), timeout=20)
        except Exception:
            return 503, "cluster verification failed"
        return (200, "cluster deletion verified") if check.status_code == 404 else (503, "cluster deletion is ongoing")
    if deleted.status_code not in (200, 202):
        return 503, "cluster deletion is temporarily unavailable"
    # GKE deletion is asynchronous. A retry receives 200 only after GET sees 404.
    try:
        verify = session.get(cluster_url(request), timeout=20)
    except Exception:
        return 503, "cluster deletion verification failed"
    if verify.status_code == 404:
        return 200, "cluster deletion verified"
    if verify.status_code == 200:
        try:
            current_cluster = verify.json()
        except Exception:
            return 503, "cluster deletion verification returned invalid data"
        current_labels = current_cluster.get("resourceLabels") if isinstance(current_cluster, dict) else None
        if not _has_ownership_labels(current_labels, request):
            return 403, "cluster ownership labels changed during deletion"
    return 503, "cluster deletion is ongoing"


def authorized_session() -> Any:
    """Import Google auth only when handling a cloud request."""
    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    return AuthorizedSession(credentials)


class ExpiryHandler(BaseHTTPRequestHandler):
    server_version = "InferenceLabExpiry/1"
    sys_version = ""

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler method name
        if self.path != "/expire":
            self._respond(404, "not found")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._respond(400, "invalid request")
            return
        if length <= 0 or length > MAX_BODY_BYTES:
            self._respond(413, "invalid request size")
            return
        try:
            payload = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._respond(400, "invalid JSON")
            return
        configured_project = os.environ.get("LAB_PROJECT_ID", "")
        if not configured_project:
            self._respond(503, "service is not configured")
            return
        try:
            session = authorized_session()
            code, message = process_expiry(payload, configured_project, session)
        except Exception:
            # Do not log request bodies or credential/provider exception details.
            code, message = 503, "expiry service is temporarily unavailable"
        self._respond(code, message)

    def _respond(self, code: int, message: str) -> None:
        body = message.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        # BaseHTTPRequestHandler logs request paths and may include untrusted input.
        return


def serve() -> None:
    server = HTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), ExpiryHandler)
    server.serve_forever()


if __name__ == "__main__":
    serve()
