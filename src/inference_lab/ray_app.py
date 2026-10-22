"""Thin Ray Serve HTTP adapter for the dependency-free serving core."""

from __future__ import annotations

import os
import asyncio

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from ray import serve

from inference_lab.serving import (
    AdmissionLimiter,
    DEFAULT_MAX_IN_FLIGHT,
    DEFAULT_MODEL_ID,
    OverloadedError,
    RequestValidationError,
    UpstreamFailure,
    UpstreamTimeout,
    forward_chat_completion,
)

REQUEST_TIMEOUT_S = 65
UPSTREAM_TIMEOUT_S = 60
BOUNDED_ONGOING_REQUESTS = 8
SERVE_CONFIG = {
    "request_timeout_s": REQUEST_TIMEOUT_S,
    "bounded_ongoing_requests": BOUNDED_ONGOING_REQUESTS,
}
api = FastAPI()


@serve.deployment(max_ongoing_requests=BOUNDED_ONGOING_REQUESTS)
@serve.ingress(api)
class InferenceAPI:
    def __init__(self):
        self.model_id = os.environ.get("MODEL_ID", DEFAULT_MODEL_ID)
        self.endpoint = os.environ.get("MODEL_ENDPOINT", "http://vllm:8000").rstrip("/")
        self.limiter = AdmissionLimiter(DEFAULT_MAX_IN_FLIGHT)
        # Kubernetes Services balance connections, so avoid pinning all requests
        # to the first model pod via one persistent connection in this tiny lab.
        self.client = httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT_S,
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=0))

    async def _post_json(self, url, payload):
        try:
            response = await self.client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise asyncio.TimeoutError() from exc
        try:
            body = response.json()
        except ValueError:
            body = None
        return response.status_code, body

    @api.get("/healthz")
    async def healthz(self):
        return {"status": "ok"}

    @api.post("/v1/chat/completions")
    async def chat_completions(self, request: Request):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 32768:
                return JSONResponse({"error": {"message": "request body exceeds 32 KiB"}}, status_code=413)
        try:
            import json
            payload = json.loads(body)
        except Exception:
            return JSONResponse({"error": {"message": "request body must be valid JSON", "type": "invalid_request_error"}}, status_code=400)
        try:
            result = await forward_chat_completion(
                payload,
                model_id=self.model_id,
                endpoint=self.endpoint,
                post_json=self._post_json,
                limiter=self.limiter,
                timeout_s=UPSTREAM_TIMEOUT_S,
            )
        except RequestValidationError as exc:
            return JSONResponse({"error": {"message": str(exc), "type": "invalid_request_error"}}, status_code=400)
        except OverloadedError as exc:
            return JSONResponse({"error": {"message": str(exc), "type": "server_error"}}, status_code=exc.status_code)
        except UpstreamTimeout as exc:
            return JSONResponse({"error": {"message": str(exc), "type": "server_error"}}, status_code=exc.status_code)
        except UpstreamFailure as exc:
            return JSONResponse({"error": {"message": str(exc), "type": "server_error"}}, status_code=exc.status_code)
        import ray
        return JSONResponse(result, headers={"X-Lab-Ray-Node": str(ray.get_runtime_context().get_node_id())})


app = InferenceAPI.bind()


if __name__ == "__main__":
    import ray

    ray.init(include_dashboard=False)
    serve.start(
        http_options={
            "host": "0.0.0.0",
            "port": 8000,
            "request_timeout_s": REQUEST_TIMEOUT_S,
        }
    )
    serve.run(app)
