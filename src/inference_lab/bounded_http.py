"""Small bounded HTTP transport for inference endpoints."""

from __future__ import annotations

import http.client
import json
import math
import socket
import threading
import time
from urllib.parse import urlsplit


def request(
    method: str,
    url: str,
    *,
    json_body: dict | None = None,
    timeout: float = 10,
    max_bytes: int = 65536,
) -> tuple[int, bytes]:
    """Make one direct HTTP request, bounding its connected lifetime and body.

    Redirects and environment proxy settings are not consulted. A successful
    response reads at most ``max_bytes + 1`` bytes so callers can detect an
    oversized body. Error responses return an empty body.
    """
    if method not in {"GET", "POST"}:
        raise ValueError("method must be GET or POST")
    if not isinstance(url, str) or not url or any(char.isspace() for char in url):
        raise ValueError("url must be an absolute http(s) URL")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("url must be a valid absolute http(s) URL") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("url must be an absolute http(s) URL")
    if parsed.username is not None or parsed.password is not None or "#" in url:
        raise ValueError("url must not contain credentials or a fragment")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be a finite positive number")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 0:
        raise ValueError("max_bytes must be a non-negative integer")
    if json_body is not None and not isinstance(json_body, dict):
        raise ValueError("json_body must be a dictionary or None")

    body = None
    headers = {"Accept": "application/json"}
    if json_body is not None:
        body = json.dumps(json_body, allow_nan=False, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"

    started = time.perf_counter()
    connection = None
    response = None
    timer = None
    deadline_fired = threading.Event()
    try:
        connection_type = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        connection = connection_type(parsed.hostname, port, timeout=float(timeout))
        # DNS lookup cannot be interrupted by Python's socket timeout. Once
        # connected, the remaining budget is enforced by shutting down this
        # captured socket even when a peer keeps dribbling response bytes.
        connection.connect()
        request_socket = connection.sock
        if request_socket is None:
            raise OSError("connection has no socket")
        remaining = timeout - (time.perf_counter() - started)
        if remaining <= 0:
            raise TimeoutError("request deadline exceeded")
        request_socket.settimeout(remaining)

        def interrupt_request() -> None:
            deadline_fired.set()
            try:
                request_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        timer = threading.Timer(remaining, interrupt_request)
        timer.daemon = True
        timer.start()
        target = parsed.path or "/"
        if parsed.query:
            target += "?" + parsed.query
        connection.request(method, target, body=body, headers=headers)
        response = connection.getresponse()
        if deadline_fired.is_set() or time.perf_counter() - started >= timeout:
            raise TimeoutError("request deadline exceeded")
        status = response.status
        if 200 <= status < 300:
            response_body = response.read(max_bytes + 1)
            if deadline_fired.is_set() or time.perf_counter() - started >= timeout:
                raise TimeoutError("request deadline exceeded")
        else:
            response_body = b""
        return status, response_body
    except (http.client.HTTPException, OSError) as exc:
        if deadline_fired.is_set() or time.perf_counter() - started >= timeout:
            raise TimeoutError("request deadline exceeded") from exc
        if isinstance(exc, http.client.HTTPException):
            raise OSError("HTTP request failed") from exc
        raise
    finally:
        if timer is not None:
            timer.cancel()
            if timer.is_alive():
                timer.join()
        if response is not None:
            response.close()
        if connection is not None:
            connection.close()
