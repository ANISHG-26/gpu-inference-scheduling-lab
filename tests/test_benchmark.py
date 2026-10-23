"""Behavioral tests for the dependency-free HTTP benchmark."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from inference_lab.benchmark import run_benchmark, summarize, validate_url, write_report


class BenchmarkServer:
    def __init__(self):
        self.requests = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(inner_self):
                body = inner_self.rfile.read(int(inner_self.headers["Content-Length"]))
                owner.requests.append(json.loads(body))
                if inner_self.path != "/v1/chat/completions":
                    inner_self.send_error(404)
                    return
                if len(owner.requests) == 2:
                    # A deliberately slow response exercises client timeout handling.
                    threading.Event().wait(0.2)
                if len(owner.requests) == 3:
                    inner_self.send_response(503)
                    inner_self.end_headers()
                    try:
                        inner_self.wfile.write(b"private backend detail")
                    except OSError:
                        pass
                    return
                payload = {
                    "choices": [{"message": {"content": "private generated text"}}],
                    "usage": {"prompt_tokens": 4, "completion_tokens": 3},
                }
                encoded = json.dumps(payload).encode()
                inner_self.send_response(200)
                inner_self.send_header("Content-Type", "application/json")
                inner_self.send_header("Content-Length", str(len(encoded)))
                inner_self.end_headers()
                try:
                    inner_self.wfile.write(encoded)
                except OSError:
                    pass

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self):
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)


class BenchmarkTests(unittest.TestCase):
    def test_slow_dribble_response_obeys_total_request_deadline(self):
        payload = b'{"choices":[{"message":{"content":"ok"}}]}'

        class SlowDribbleHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                try:
                    for byte in payload:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        threading.Event().wait(0.02)
                except OSError:
                    pass

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), SlowDribbleHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            report = run_benchmark(
                f"http://127.0.0.1:{server.server_port}", requests=1, timeout=0.08
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        metric = report["requests"][0]
        self.assertEqual(metric["error"], "timeout")
        self.assertLess(metric["elapsed_seconds"], 0.25)

    def test_oversized_success_is_not_accepted_and_read_is_bounded(self):
        payload = b" " * 65537

        class OversizedHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), OversizedHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            report = run_benchmark(f"http://127.0.0.1:{server.server_port}", requests=1)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)
        self.assertEqual(report["summary"]["completed"], 0)
        self.assertEqual(report["requests"][0]["error"], "invalid_response")

    def test_redirect_is_not_followed(self):
        visited = []

        class RedirectHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                visited.append(self.path)
                self.send_response(302)
                self.send_header("Location", "/unexpected")
                self.end_headers()

            def do_GET(self):
                visited.append(self.path)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"choices":[{"message":{"content":"redirected"}}]}')

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            report = run_benchmark(f"http://127.0.0.1:{server.server_port}", requests=1)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)
        self.assertEqual(visited, ["/v1/chat/completions"])
        self.assertEqual(report["summary"]["completed"], 0)

    def test_local_server_records_success_timeout_and_http_error_without_contents(self):
        with BenchmarkServer() as server:
            report = run_benchmark(
                server.url, requests=3, concurrency=1, max_tokens=7, timeout=0.05
            )

        self.assertEqual(report["summary"]["completed"], 1)
        self.assertEqual(report["summary"]["errors"], 2)
        self.assertEqual(report["requests"][0]["prompt_tokens"], 4)
        self.assertEqual(report["requests"][0]["completion_tokens"], 3)
        self.assertEqual(report["requests"][1]["error"], "timeout")
        self.assertEqual(report["requests"][2]["status"], 503)
        serialized = json.dumps(report)
        self.assertNotIn("private generated text", serialized)
        self.assertNotIn("private backend detail", serialized)
        self.assertEqual(len(server.requests), 3)
        for payload in server.requests:
            self.assertEqual(payload["model"], "Qwen/Qwen3-0.6B")
            self.assertEqual(payload["max_tokens"], 7)
            self.assertFalse(payload["stream"])

    def test_summary_uses_nearest_rank_percentiles_and_wall_time_throughput(self):
        report = summarize(
            [
                {"elapsed_seconds": 1.0, "completion_tokens": 2, "completed": True},
                {"elapsed_seconds": 2.0, "completion_tokens": 4, "completed": True},
                {"elapsed_seconds": 8.0, "completion_tokens": None, "completed": False},
                {"elapsed_seconds": 3.0, "completion_tokens": 8, "completed": True},
            ],
            wall_time_seconds=4.0,
        )
        self.assertEqual(report["completed"], 3)
        self.assertEqual(report["errors"], 1)
        self.assertEqual(report["p50_latency_seconds"], 2.0)
        self.assertEqual(report["p95_latency_seconds"], 3.0)
        self.assertEqual(report["completion_tokens_per_second"], 3.5)

    def test_url_validation_and_exclusive_output(self):
        for url in (
            "ftp://localhost",
            "http://user:secret@localhost",
            "http://localhost/?token=x",
            "http://localhost/?",
            "http://localhost/#fragment",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_url(url)
        for options in (
            {"requests": 0},
            {"requests": 101},
            {"concurrency": 9},
            {"max_tokens": 129},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                run_benchmark("http://127.0.0.1:1", **options)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            write_report(path, {"summary": {"completed": 0}})
            with self.assertRaises(FileExistsError):
                write_report(path, {"summary": {"completed": 0}})


if __name__ == "__main__":
    unittest.main()
