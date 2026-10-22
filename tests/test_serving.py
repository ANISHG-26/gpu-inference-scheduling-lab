"""Behavioral contract for the dependency-free serving core."""

import asyncio
from pathlib import Path
import sys
import unittest

# The local Windows sandbox can stall the default Proactor loop in test
# subprocesses. Production code leaves the platform policy untouched.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from inference_lab.serving import (
    AdmissionLimiter,
    OverloadedError,
    RequestValidationError,
    UpstreamFailure,
    UpstreamTimeout,
    forward_chat_completion,
    validate_chat_completion,
)


class RequestValidationTests(unittest.TestCase):
    def setUp(self):
        self.valid = {
            "model": "Qwen/Qwen3-0.6B",
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 32,
        }

    def test_accepts_bounded_nonstreaming_chat_request(self):
        self.assertEqual(validate_chat_completion(self.valid, "Qwen/Qwen3-0.6B"), self.valid)

    def test_rejects_wrong_model_streaming_and_unknown_parameters(self):
        for update in (
            {"model": "another-model"},
            {"stream": True},
            {"temperature": 0},
        ):
            with self.subTest(update=update), self.assertRaises(RequestValidationError):
                validate_chat_completion(self.valid | update, "Qwen/Qwen3-0.6B")

    def test_rejects_message_and_token_boundaries(self):
        cases = [
            self.valid | {"max_tokens": 0},
            self.valid | {"max_tokens": 129},
            self.valid | {"messages": [{"role": "user", "content": "x"}] * 17},
            self.valid | {"messages": [{"role": "user", "content": "x" * 4097}]},
            self.valid | {"messages": [{"role": "user", "content": ["not", "text"]}]},
        ]
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(RequestValidationError):
                validate_chat_completion(payload, "Qwen/Qwen3-0.6B")


class ForwardingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.payload = {
            "model": "Qwen/Qwen3-0.6B",
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 8,
        }

    async def test_forwards_validated_request_and_returns_success_body(self):
        seen = []

        async def post(url, payload):
            seen.append((url, payload))
            return 200, {"choices": [{"message": {"content": "hi"}}]}

        result = await forward_chat_completion(
            self.payload, model_id="Qwen/Qwen3-0.6B", endpoint="http://vllm:8000",
            post_json=post, limiter=AdmissionLimiter(1), timeout_s=0.5,
        )
        self.assertEqual(result, {"choices": [{"message": {"content": "hi"}}]})
        self.assertEqual(seen, [("http://vllm:8000/v1/chat/completions", self.payload)])

    async def test_rejects_overload_without_waiting_for_a_slot(self):
        entered = asyncio.Event()
        release = asyncio.Event()

        async def post(url, payload):
            entered.set()
            await release.wait()
            return 200, {"ok": True}

        limiter = AdmissionLimiter(1)
        first = asyncio.create_task(forward_chat_completion(
            self.payload, model_id="Qwen/Qwen3-0.6B", endpoint="http://vllm:8000",
            post_json=post, limiter=limiter, timeout_s=1,
        ))
        await entered.wait()
        try:
            with self.assertRaises(OverloadedError) as caught:
                await forward_chat_completion(
                    self.payload, model_id="Qwen/Qwen3-0.6B", endpoint="http://vllm:8000",
                    post_json=post, limiter=limiter, timeout_s=1,
                )
            self.assertEqual(caught.exception.status_code, 429)
            self.assertEqual(await limiter.in_flight(), 1)
        finally:
            release.set()
            await first
        self.assertEqual(await limiter.in_flight(), 0)

    async def test_timeout_and_upstream_error_are_sanitized(self):
        async def slow(url, payload):
            await asyncio.sleep(1)
            return 200, {"ok": True}

        with self.assertRaises(UpstreamTimeout):
            await forward_chat_completion(
                self.payload, model_id="Qwen/Qwen3-0.6B", endpoint="http://vllm:8000",
                post_json=slow, limiter=AdmissionLimiter(1), timeout_s=0.01,
            )

        async def failed(url, payload):
            return 503, {"detail": "private model server traceback"}

        with self.assertRaises(UpstreamFailure) as caught:
            await forward_chat_completion(
                self.payload, model_id="Qwen/Qwen3-0.6B", endpoint="http://vllm:8000",
                post_json=failed, limiter=AdmissionLimiter(1), timeout_s=0.5,
            )
        self.assertEqual(caught.exception.status_code, 502)
        self.assertNotIn("private model server traceback", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
