"""Behavioral tests for the dependency-free bounded HTTP transport."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from inference_lab.bounded_http import request


class BoundedHttpTests(unittest.TestCase):
    def test_direct_get_post_redirect_and_bounded_response_contract(self):
        observed = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                observed.append(("GET", self.path, None))
                if self.path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", "/target")
                    self.end_headers()
                elif self.path == "/error":
                    self.send_response(503)
                    self.end_headers()
                    self.wfile.write(b"private detail")
                else:
                    payload = b"0123456789"
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                observed.append(("POST", self.path, json.loads(body)))
                self.send_response(201)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        url = f"http://127.0.0.1:{server.server_port}"
        try:
            # A deliberately unusable proxy proves that the transport connects
            # directly and does not consult proxy environment variables.
            with patch.dict(
                "os.environ",
                {
                    "HTTP_PROXY": "http://127.0.0.1:1",
                    "http_proxy": "http://127.0.0.1:1",
                    "HTTPS_PROXY": "http://127.0.0.1:1",
                    "https_proxy": "http://127.0.0.1:1",
                },
                clear=True,
            ):
                self.assertEqual(request("GET", url + "/small", max_bytes=4), (200, b"01234"))
                self.assertEqual(request("POST", url + "/submit", json_body={"ok": True}), (201, b""))
                self.assertEqual(request("GET", url + "/redirect"), (302, b""))
                self.assertEqual(request("GET", url + "/error"), (503, b""))
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=1)

        self.assertEqual([item[:2] for item in observed], [
            ("GET", "/small"),
            ("POST", "/submit"),
            ("GET", "/redirect"),
            ("GET", "/error"),
        ])
        self.assertEqual(observed[1][2], {"ok": True})

    def test_rejects_unsupported_method_and_non_finite_json(self):
        with self.assertRaises(ValueError):
            request("PUT", "http://127.0.0.1:1")
        with self.assertRaises(ValueError):
            request("POST", "http://127.0.0.1:1", json_body={"value": float("nan")})


if __name__ == "__main__":
    unittest.main()
