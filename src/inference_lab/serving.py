"""Dependency-free request validation and bounded async forwarding primitives."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Awaitable, Callable

DEFAULT_MODEL_ID = "Qwen/Qwen3-0.6B"
DEFAULT_MAX_IN_FLIGHT = 8
MAX_MESSAGES = 16
MAX_TOTAL_CHARS = 4096
MAX_TOKENS = 128


class RequestValidationError(Exception):
    """Client supplied a request outside the supported chat subset."""


class OverloadedError(Exception):
    """The service has no free upstream request slot."""

    status_code = 429

    def __str__(self) -> str:
        return "inference service is at capacity"


class UpstreamFailure(Exception):
    """The model endpoint failed; its response body is intentionally discarded."""

    def __init__(self, status_code: int = 502):
        self.status_code = status_code
        super().__init__("model endpoint request failed")


class UpstreamTimeout(Exception):
    """The model endpoint did not respond within the configured deadline."""

    status_code = 504

    def __str__(self) -> str:
        return "model endpoint request timed out"


class AdmissionLimiter:
    """An immediate-rejection, bounded in-flight admission counter."""

    def __init__(self, limit: int = DEFAULT_MAX_IN_FLIGHT):
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        self.limit = limit
        self._active = 0
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def slot(self):
        async with self._lock:
            if self._active >= self.limit:
                raise OverloadedError()
            self._active += 1
        try:
            yield
        finally:
            async with self._lock:
                self._active -= 1

    async def in_flight(self) -> int:
        async with self._lock:
            return self._active


def validate_chat_completion(payload: Any, model_id: str = DEFAULT_MODEL_ID) -> dict[str, Any]:
    """Validate the deliberately small, non-streaming OpenAI-compatible subset."""
    if not isinstance(payload, dict):
        raise RequestValidationError("request body must be a JSON object")
    allowed = {"model", "messages", "max_tokens", "stream"}
    unknown = set(payload) - allowed
    if unknown:
        raise RequestValidationError("request contains unsupported fields")
    if payload.get("model") != model_id:
        raise RequestValidationError("model must match the configured model")
    if payload.get("stream", False) is not False:
        raise RequestValidationError("streaming is not supported")
    if "max_tokens" not in payload:
        raise RequestValidationError("max_tokens is required")
    max_tokens = payload["max_tokens"]
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= MAX_TOKENS:
        raise RequestValidationError("max_tokens must be an integer from 1 to 128")
    messages = payload.get("messages")
    if not isinstance(messages, list) or not 1 <= len(messages) <= MAX_MESSAGES:
        raise RequestValidationError("messages must contain 1 to 16 entries")
    total_chars = 0
    for message in messages:
        if not isinstance(message, dict) or set(message) != {"role", "content"}:
            raise RequestValidationError("each message must contain only role and content")
        if not isinstance(message["role"], str) or message["role"] not in {"system", "user", "assistant"}:
            raise RequestValidationError("message role is unsupported")
        if not isinstance(message["content"], str):
            raise RequestValidationError("message content must be text")
        total_chars += len(message["role"]) + len(message["content"])
        if total_chars > MAX_TOTAL_CHARS:
            raise RequestValidationError("messages exceed the 4096 character limit")
    # Return only the fields that were explicitly accepted. stream:false is
    # permitted but is omitted from the upstream body because it is the default.
    return {
        "model": model_id,
        "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
        "max_tokens": max_tokens,
    }


async def forward_chat_completion(
    payload: Any,
    *,
    model_id: str,
    endpoint: str,
    post_json: Callable[[str, dict[str, Any]], Awaitable[tuple[int, Any]]],
    limiter: AdmissionLimiter,
    timeout_s: float = 60,
) -> Any:
    """Validate, admit, and forward one request while sanitizing model errors."""
    request = validate_chat_completion(payload, model_id)
    url = endpoint.rstrip("/") + "/v1/chat/completions"
    async with limiter.slot():
        try:
            status, body = await asyncio.wait_for(post_json(url, request), timeout=timeout_s)
        except asyncio.TimeoutError as exc:
            raise UpstreamTimeout() from exc
        except Exception as exc:
            raise UpstreamFailure() from exc
        if not 200 <= status < 300 or not isinstance(body, dict):
            raise UpstreamFailure()
        return body
