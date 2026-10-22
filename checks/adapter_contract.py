"""Exercise the Ray adapter's HTTP boundaries without starting Ray processes."""
import unittest
from unittest.mock import AsyncMock, patch
from inference_lab.ray_app import InferenceAPI

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

if __name__ == "__main__":
    unittest.main()
