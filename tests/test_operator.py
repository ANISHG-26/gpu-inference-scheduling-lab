"""Focused tests for the same-origin lab operator boundary."""

from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from inference_lab import operator


def pod(name, uid, role="model", node="node-a", *, ready=True, phase="Running", owner="vllm", terminating=False):
    if role == "model":
        labels = {"app": "vllm"}
        kind = "StatefulSet"
    else:
        labels = {
            "ray.io/node-type": "head" if role == "Ray head" else "worker",
            "ray.io/cluster": owner,
            "ray.io/serve": "true",
            "is-ray-node": "yes",
        }
        kind = "RayCluster"
    meta = {"name": name, "uid": uid, "labels": labels,
            "ownerReferences": [{"controller": True, "kind": kind, "name": owner}]}
    if terminating:
        meta["deletionTimestamp"] = "2026-10-22T00:00:00Z"
    return {"metadata": meta, "spec": {"nodeName": node},
            "status": {"phase": phase, "conditions": [{"type": "Ready", "status": "True" if ready else "False"}]}}


class OperatorHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        (root / "index.html").write_text("ok", encoding="utf-8")
        (root / "app.js").write_text("", encoding="utf-8")
        (root / "style.css").write_text("", encoding="utf-8")
        self.server = operator._BoundedServer(("127.0.0.1", 0), operator.OperatorHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.server_address
        self.origin = f"http://{self.host}:{self.port}"
        self.static_patch = patch.object(operator, "STATIC_ROOT", root)
        self.static_patch.start()
        self.exp_patch = patch.dict(operator.os.environ, {
            "ACTIVE_LESSON": "01-single-node-inference",
            "LAB_EXPIRES_AT": str(int(time.time()) + 7200),
            "LAB_ACTIONS_ENABLED": "true",
            "EXPECTED_RAY_CLUSTER": "cluster",
        })
        self.exp_patch.start()
        operator.EXPERIMENT = None
        operator.EXPERIMENT_RUNNING = False

    def tearDown(self):
        self.exp_patch.stop()
        self.static_patch.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)
        self.temp.cleanup()
        operator.EXPERIMENT = None
        operator.EXPERIMENT_RUNNING = False

    def call(self, path, payload=None, *, host=None, origin=None, content_type="application/json"):
        body = None if payload is None else json.dumps(payload).encode()
        headers = {"Host": host or f"127.0.0.1:{self.port}"}
        if body is not None:
            headers.update({"Content-Type": content_type, "Origin": self.origin if origin is None else origin})
        req = Request(self.origin + path, data=body, headers=headers, method="POST" if body is not None else "GET")
        try:
            with urlopen(req, timeout=2) as response:
                return response.status, response.headers, response.read()
        except HTTPError as exc:
            return exc.code, exc.headers, exc.read()

    def test_host_origin_body_and_static_allowlist(self):
        self.assertEqual(self.call("/healthz")[0], 200)
        code, headers, body = self.call("/secret")
        self.assertEqual(code, 404)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(self.call("/", host="attacker.example:8080")[0], 421)
        self.assertEqual(self.call("/api/experiments", {"lesson_id": "01-single-node-inference", "concurrency": 1}, origin="http://attacker.example")[0], 403)
        self.assertEqual(self.call("/api/experiments", {"lesson_id": "01-single-node-inference", "concurrency": True})[0], 400)
        self.assertEqual(self.call("/api/experiments", {"lesson_id": "01-single-node-inference", "concurrency": 1, "url": "http://evil"})[0], 400)
        self.assertEqual(self.call("/api/experiments", {"lesson_id": "03-slurm-cpu-scheduling", "concurrency": 1})[0], 400)
        self.assertEqual(self.call("/api/experiments", {"lesson_id": [], "concurrency": 1})[0], 400)

    def test_rejected_post_closes_connection_before_embedded_request_can_run(self):
        inner_body = b'{"lesson_id":"01-single-node-inference","concurrency":8}'
        embedded = (
            f"POST /api/experiments HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{self.port}\r\n"
            f"Origin: {self.origin}\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(inner_body)}\r\n\r\n"
        ).encode() + inner_body
        outer = (
            f"POST /api/experiments HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{self.port}\r\n"
            "Origin: http://attacker.invalid\r\n"
            "Content-Type: text/plain\r\n"
            f"Content-Length: {len(embedded)}\r\n"
            "Connection: keep-alive\r\n\r\n"
        ).encode() + embedded
        with patch.object(operator, "_snapshot") as snapshot, patch.object(operator.benchmark, "run_benchmark") as run_benchmark:
            with socket.create_connection((self.host, self.port), timeout=2) as conn:
                conn.settimeout(2)
                conn.sendall(outer)
                conn.shutdown(socket.SHUT_WR)
                chunks = []
                while True:
                    data = conn.recv(4096)
                    if not data:
                        break
                    chunks.append(data)
            response = b"".join(chunks)
        self.assertIn(b"HTTP/1.1 403", response)
        self.assertEqual(response.count(b"HTTP/1.1 "), 1)
        self.assertIn(b"Connection: close", response)
        snapshot.assert_not_called()
        run_benchmark.assert_not_called()

    def test_placement_requires_controller_readiness_and_distinct_nodes(self):
        single = [pod("vllm-0", "u0"), pod("head", "h0", "Ray head", owner="cluster"), pod("worker", "w0", "Ray worker", owner="cluster")]
        self.assertTrue(operator._placement("01-single-node-inference", operator._safe_pods(single))["valid"])
        self.assertFalse(operator._placement("01-single-node-inference", operator._safe_pods(single[:1]))["valid"])
        two_same_node = [pod("vllm-0", "u0"), pod("vllm-1", "u1"),
                         pod("head", "h0", "Ray head", owner="cluster"),
                         pod("worker-0", "w0", "Ray worker", node="node-a", owner="cluster"),
                         pod("worker-1", "w1", "Ray worker", node="node-b", owner="cluster")]
        self.assertFalse(operator._placement("02-two-node-inference", operator._safe_pods(two_same_node))["valid"])
        two_nodes = [pod("vllm-0", "u0", node="node-a"), pod("vllm-1", "u1", node="node-b"),
                     pod("head", "h0", "Ray head", node="node-a", owner="cluster"),
                     pod("worker-0", "w0", "Ray worker", node="node-a", owner="cluster"),
                     pod("worker-1", "w1", "Ray worker", node="node-b", owner="cluster")]
        self.assertTrue(operator._placement("02-two-node-inference", operator._safe_pods(two_nodes))["valid"])
        wrong_owner = [pod("vllm-0", "u0", owner="other")]
        self.assertFalse(operator._placement("01-single-node-inference", operator._safe_pods(wrong_owner))["valid"])
        self.assertFalse(operator._placement("03-slurm-cpu-scheduling", operator._safe_pods(single))["valid"])
        mismatched = operator._safe_pods([*single, pod("head-old", "h1", "Ray head", owner="old-cluster")])
        self.assertFalse(operator._placement("01-single-node-inference", mismatched)["valid"])
        with patch.dict(operator.os.environ, {"EXPECTED_RAY_CLUSTER": ""}):
            self.assertFalse(operator._placement("01-single-node-inference", operator._safe_pods(single))["valid"])

    def test_state_is_prepared_when_api_unavailable_and_hides_owner_metadata(self):
        lessons = ({"id": "01-single-node-inference", "title": "Single", "objective": "x", "steps": [], "prediction": "x", "reflection": "x", "gate": None},)
        with patch.object(operator, "_catalog", return_value=lessons), patch.object(operator, "_list_pods", side_effect=OSError("private credential detail")):
            result = operator.state()
        self.assertEqual(result["observation"]["status"], "unavailable")
        self.assertEqual(result["lessons"][0]["state"], "prepared")
        self.assertNotIn("credential", json.dumps(result))

    def test_expiry_and_concurrent_experiment_admission(self):
        self.assertEqual(operator._loopback_host("[::1]:8080"), True)
        self.assertEqual(operator._loopback_host("127.0.0.1:8080.evil"), False)
        with patch.dict(operator.os.environ, {"LAB_EXPIRES_AT": str(int(time.time()) - 1)}):
            self.assertEqual(operator._session()["status"], "expired")
        serving = [pod("vllm-0", "uid-current"), pod("head", "head-current", "Ray head", owner="cluster"), pod("worker", "worker-current", "Ray worker", owner="cluster")]
        snapshot = {"status": "ok", "pods": operator._safe_pods(serving), "placement": {"valid": True, "reason": "ready"}}
        entered, release = threading.Event(), threading.Event()

        def blocking_benchmark(*_args, **_kwargs):
            entered.set()
            release.wait(1)
            return {"requests": [], "summary": {"completed": 0}}

        with patch.object(operator, "_snapshot", return_value=snapshot), patch.object(operator.benchmark, "run_benchmark", side_effect=blocking_benchmark):
            self.assertEqual(self.call("/api/experiments", {"lesson_id": "01-single-node-inference", "concurrency": 8})[0], 202)
            self.assertTrue(entered.wait(1))
            self.assertEqual(self.call("/api/experiments", {"lesson_id": "01-single-node-inference", "concurrency": 8})[0], 409)
            release.set()
            limit = time.time() + 2
            while operator.EXPERIMENT_RUNNING and time.time() < limit:
                time.sleep(0.01)
        operator.EXPERIMENT = {"id": "e", "lesson_id": "01-single-node-inference", "state": "measured", "pod_uids": {"old"}}
        with patch.object(operator, "_snapshot", return_value=snapshot), patch.object(operator, "_catalog", return_value=({"id": "01-single-node-inference", "title": "Single", "objective": "x", "steps": [], "prediction": "x", "reflection": "x", "gate": None},)):
            result = operator.state()
        self.assertEqual(result["lessons"][0]["state"], "failed")
        self.assertEqual(operator.EXPERIMENT["error"], "pod_identity_changed")

    def test_measured_state_invalidates_when_readiness_api_or_session_is_stale(self):
        lessons = ({"id": "01-single-node-inference", "title": "Single", "objective": "x", "steps": [], "prediction": "x", "reflection": "x", "gate": None},)
        serving = operator._safe_pods([
            pod("vllm-0", "uid-current"),
            pod("head", "head-current", "Ray head", owner="cluster"),
            pod("worker", "worker-current", "Ray worker", owner="cluster"),
        ])
        cases = (
            ({"status": "ok", "observed_at": 1, "pods": serving, "placement": {"valid": False, "reason": "not ready"}}, "placement_unready", "active"),
            ({"status": "unavailable", "observed_at": 1, "pods": [], "placement": {"valid": False, "reason": "unavailable"}}, "observation_unavailable", "active"),
            ({"status": "ok", "observed_at": 1, "pods": serving, "placement": {"valid": True, "reason": "ready"}}, "session_expired", "expired"),
        )
        for observation, error, session_status in cases:
            with self.subTest(error=error):
                operator.EXPERIMENT = {"id": "e", "lesson_id": "01-single-node-inference", "state": "measured", "pod_uids": {"uid-current", "head-current", "worker-current"}, "summary": {"completed": 8}}
                with patch.object(operator, "_snapshot", return_value=observation), patch.object(operator, "_catalog", return_value=lessons), patch.object(operator, "_session", return_value={"expires_at": 1, "remaining_seconds": 0, "status": session_status}):
                    result = operator.state()
                self.assertEqual(result["lessons"][0]["state"], "failed")
                self.assertEqual(result["experiment"]["state"], "failed")
                self.assertEqual(result["experiment"]["error"], error)
                self.assertEqual(result["experiment"]["summary"], {"completed": 8})
                with patch.object(operator, "_snapshot", return_value=observation), patch.object(operator, "_catalog", return_value=lessons), patch.object(operator, "_session", return_value={"expires_at": 1, "remaining_seconds": 0, "status": session_status}):
                    next_poll = operator.state()
                self.assertEqual(next_poll["lessons"][0]["state"], "failed")
                self.assertEqual(next_poll["lessons"][0]["reason"], result["lessons"][0]["reason"])

    def test_request_failure_remains_visible_until_next_run(self):
        lessons = ({"id": "01-single-node-inference", "title": "Single", "objective": "x", "steps": [], "prediction": "x", "reflection": "x", "gate": None},)
        serving = operator._safe_pods([
            pod("vllm-0", "uid-current"),
            pod("head", "head-current", "Ray head", owner="cluster"),
            pod("worker", "worker-current", "Ray worker", owner="cluster"),
        ])
        observation = {"status": "ok", "observed_at": 1, "pods": serving, "placement": {"valid": True, "reason": "ready"}}
        operator.EXPERIMENT = {"id": "failed-run", "lesson_id": "01-single-node-inference", "state": "failed", "error": "requests_failed", "summary": {"completed": 6}}
        with patch.object(operator, "_snapshot", return_value=observation), patch.object(operator, "_catalog", return_value=lessons):
            first = operator.state()
            second = operator.state()
        self.assertEqual(first["lessons"][0]["state"], "failed")
        self.assertEqual(second["lessons"][0]["state"], "failed")
        self.assertEqual(second["lessons"][0]["reason"], "One or more benchmark requests failed.")

    def test_post_run_expiry_and_api_outage_keep_partial_metrics(self):
        metrics = [{"completed": True, "completion_tokens": 3, "elapsed_seconds": 0.1} for _ in range(8)]
        report = {"requests": metrics, "summary": {"completed": 8}}
        serving = operator._safe_pods([
            pod("vllm-0", "uid-current"),
            pod("head", "head-current", "Ray head", owner="cluster"),
            pod("worker", "worker-current", "Ray worker", owner="cluster"),
        ])
        healthy = {"status": "ok", "observed_at": 1, "pods": serving, "placement": {"valid": True, "reason": "ready"}}
        unavailable = {"status": "unavailable", "observed_at": 1, "pods": [], "placement": {"valid": False, "reason": "unavailable"}}
        before = {"uid-current", "head-current", "worker-current"}
        cases = (([{"status": "active"}, {"status": "active"}], unavailable, "observation_unavailable"),
                 ([{"status": "active"}, {"status": "expired"}], healthy, "session_expired"))
        for session_states, after, error in cases:
            with self.subTest(error=error):
                operator.EXPERIMENT = None
                with patch.object(operator, "_session", side_effect=session_states), patch.object(operator, "_snapshot", return_value=after), patch.object(operator.benchmark, "run_benchmark", return_value=report):
                    operator._run_experiment("e", "01-single-node-inference", 8, before)
                self.assertEqual(operator.EXPERIMENT["state"], "failed")
                self.assertEqual(operator.EXPERIMENT["error"], error)
                self.assertEqual(operator.EXPERIMENT["summary"]["completed"], 8)
        self.assertIn("model identity is unknown", operator.EXPERIMENT["identity_note"])


if __name__ == "__main__":
    unittest.main()
