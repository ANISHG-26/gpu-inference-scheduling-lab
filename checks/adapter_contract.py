"""Exercise the Ray adapter's HTTP boundaries without starting Ray processes."""
import unittest
import inspect
from unittest.mock import AsyncMock, patch
from inference_lab.ray_app import InferenceAPI, api

class Incoming:
    def __init__(self, chunks):
        self.chunks = chunks
    async def stream(self):
        for chunk in self.chunks:
            yield chunk

class Adapter(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Ray's generated ingress wrapper surrounds the original application class.
        self.api = InferenceAPI.func_or_class.__mro__[1]()
    async def asyncTearDown(self):
        await self.api.client.aclose()

    @staticmethod
    def frozen_ingress_app():
        return inspect.getclosurevars(InferenceAPI.func_or_class.__init__).nonlocals[
            "frozen_app_or_func"
        ]

    async def test_chunked_oversize_body_is_rejected_before_forwarding(self):
        with patch("inference_lab.ray_app.forward_chat_completion", new_callable=AsyncMock) as forward:
            response = await self.api.chat_completions(Incoming([b"a" * 16384, b"b" * 16385]))
            self.assertEqual(response.status_code, 413)
            forward.assert_not_called()
    async def test_malformed_json_is_rejected_without_upstream_call(self):
        with patch("inference_lab.ray_app.forward_chat_completion", new_callable=AsyncMock) as forward:
            response = await self.api.chat_completions(Incoming([b"{"]))
            self.assertEqual(response.status_code, 400)
            forward.assert_not_called()

    def test_fastapi_chat_route_binds_asgi_request_not_class_instance(self):
        route = next(
            route
            for route in self.frozen_ingress_app().routes
            if getattr(route, "path", None) == "/v1/chat/completions"
        )
        self.assertEqual(route.dependant.request_param_name, "request")
        self.assertNotIn("self", [param.name for param in route.dependant.query_params])

    async def test_chat_asgi_route_reads_request_body_and_forwards(self):
        import httpx

        result = {"choices": [{"message": {"role": "assistant", "content": "fixture"}}]}
        with patch("inference_lab.ray_app.forward_chat_completion", new_callable=AsyncMock,
                   return_value=result) as forward, \
             patch("ray.serve.get_replica_context") as replica_context, \
             patch("ray.get_runtime_context") as runtime_context:
            replica_context.return_value.servable_object = self.api
            runtime_context.return_value.get_node_id.return_value = "fixture-node"
            transport = httpx.ASGITransport(app=self.frozen_ingress_app())
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post("/v1/chat/completions", json={
                    "model": "test", "messages": [{"role": "user", "content": "hello"}],
                    "max_tokens": 8,
                })

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["X-Lab-Ray-Node"], "fixture-node")
        forward.assert_awaited_once()

if __name__ == "__main__":
    unittest.main()
