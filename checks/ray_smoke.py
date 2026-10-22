"""Linux CI integration with Ray and a local HTTP fixture, never model evidence."""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
import ray
from ray import serve

class Fixture(BaseHTTPRequestHandler):
    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert payload["max_tokens"] == 8
        body = json.dumps({"choices": [{"message": {"role": "assistant", "content": "fixture"}}],
                           "usage": {"completion_tokens": 1, "prompt_tokens": 4}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args):
        pass

server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
os.environ["MODEL_ENDPOINT"] = f"http://127.0.0.1:{server.server_port}"
from inference_lab.ray_app import app
try:
    ray.init(num_cpus=2, include_dashboard=False)
    serve.start(http_options={"host": "127.0.0.1", "port": 8000, "request_timeout_s": 65})
    serve.run(app)
    payload = {"model": "Qwen/Qwen3-0.6B", "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 8}
    request = Request("http://127.0.0.1:8000/v1/chat/completions", data=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=70) as response:
        assert response.status == 200
        assert response.headers["X-Lab-Ray-Node"]
        assert json.load(response)["usage"]["completion_tokens"] == 1
    print("Ray Serve -> local HTTP fixture integration passed (no real model)")
finally:
    serve.shutdown()
    ray.shutdown()
    server.shutdown()
    server.server_close()
