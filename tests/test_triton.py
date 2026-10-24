"""Behavioral tests against a local HTTP protocol fixture, not runtime acceptance."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import unittest
from unittest.mock import patch

from inference_lab import triton


class TritonFixtureTests(unittest.TestCase):
    def setUp(self):
        self.stats = {"success": 0, "inference_count": 0, "execution_count": 0}
        self.requests = []
        self.bad_output = False
        self.response_model_name = "lab_double"
        self.response_model_version = "1"
        self.response_shape = None
        self.response_data = None
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def reply(self, status, body=None):
                self.send_response(status)
                if body is not None:
                    raw = json.dumps(body).encode()
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                else:
                    self.send_header("Content-Length", "0")
                    self.end_headers()

            def do_GET(self):
                if self.path.endswith("/ready"):
                    self.reply(200)
                elif self.path.endswith("/config"):
                    self.reply(200, {"name": "lab_double", "backend": "python"})
                elif self.path.endswith("/stats"):
                    self.reply(200, {"model_stats": [{
                        "name": "lab_double", "version": "1",
                        "inference_count": str(owner.stats["inference_count"]),
                        "execution_count": str(owner.stats["execution_count"]),
                        "inference_stats": {"success": {"count": str(owner.stats["success"])}},
                    }]})
                elif self.path == "/v2/models/lab_double/versions/1":
                    self.reply(200, {"name": "lab_double", "versions": ["1"], "inputs": [
                        {"name": "INPUT", "datatype": "FP32", "shape": [-1, 4]}], "outputs": [
                        {"name": "OUTPUT", "datatype": "FP32", "shape": [-1, 4]}]})
                else:
                    self.reply(404)

            def do_POST(self):
                owner.requests.append(self.path)
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
                if self.path.endswith("/versions/2/infer"):
                    self.reply(404)
                    return
                tensor = payload["inputs"][0]
                if tensor["shape"] == [1, 3]:
                    self.reply(400)
                    return
                data = tensor["data"]
                shape = tensor["shape"]
                owner.stats["success"] += 1
                owner.stats["inference_count"] += shape[0]
                owner.stats["execution_count"] += 1
                result = [float(value * 2) for value in data]
                if owner.bad_output and len(owner.requests) == 1:
                    result[0] = -1.0
                self.reply(200, {
                    "model_name": owner.response_model_name,
                    "model_version": owner.response_model_version,
                    "outputs": [{"name": "OUTPUT", "datatype": "FP32", "shape": owner.response_shape if owner.response_shape is not None else shape,
                                "data": owner.response_data if owner.response_data is not None else result}],
                })

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_patch = patch.object(triton, "TRITON_BASE", f"http://127.0.0.1:{self.server.server_port}")
        self.base_patch.start()

    def tearDown(self):
        self.base_patch.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_fixed_protocol_runs_eight_inputs_with_exact_group_count_and_probes(self):
        result = triton.run_experiment(2, 4, lambda: True)
        self.assertIsNone(result["error"])
        self.assertEqual(result["summary"]["completed"], 8)
        self.assertEqual(result["summary"]["errors"], 0)
        self.assertEqual(result["summary"]["requests_completed"], 2)
        self.assertEqual(result["summary"]["request_errors"], 0)
        self.assertEqual(result["triton"]["counter_deltas"], {"success": 2, "inference_count": 8, "execution_count": 2})
        self.assertEqual(result["triton"]["negative_probes"], {"invalid_shape_status": 400, "missing_version_status": 404})
        self.assertEqual(sum(path.endswith("/infer") for path in self.requests), 4)
        self.assertEqual(sum("/versions/2/infer" in path for path in self.requests), 1)

    def test_invalid_enums_reject_booleans_and_do_not_contact_server(self):
        for value in (True, False, 0, 3, 9, "2"):
            with self.subTest(value=value):
                result = triton.run_experiment(value, 1, lambda: True)
                self.assertIsNotNone(result["error"])
        self.assertEqual(self.requests, [])
        with self.assertRaises(ValueError):
            triton.required_seconds(1, True)

    def test_required_seconds_covers_protocol_probe_and_observation_budget(self):
        # One inference wave (10s), twelve bounded GETs (36s), two probes (20s),
        # and at least ten seconds of margin.
        self.assertGreaterEqual(triton.required_seconds(8, 8), 76)
        self.assertGreaterEqual(triton.required_seconds(1, 1), 80 + 8 * 10)

    def test_expiry_before_first_wave_makes_no_inference_requests(self):
        checks = iter([True, False])
        result = triton.run_experiment(1, 1, lambda: next(checks))
        self.assertEqual(result["error"], "session expired")
        self.assertEqual(self.requests, [])

    def test_expiry_is_checked_after_each_wave_and_keeps_real_completion(self):
        checks = iter([True, True, False])
        result = triton.run_experiment(1, 8, lambda: next(checks))
        self.assertEqual(result["error"], "session expired")
        self.assertEqual(result["summary"]["completed"], 8)
        self.assertEqual(sum(path.endswith("/infer") for path in self.requests), 1)

    def test_expiry_between_negative_probes_stops_the_second_probe(self):
        checks = iter([True, True, True, True, True, False])
        result = triton.run_experiment(8, 8, lambda: next(checks))
        self.assertEqual(result["error"], "session expired")
        self.assertEqual(sum("/versions/2/infer" in path for path in self.requests), 0)
        self.assertEqual(sum(path.endswith("/infer") for path in self.requests), 2)

    def test_wrong_tensor_result_is_not_counted_as_completed(self):
        self.bad_output = True
        result = triton.run_experiment(1, 4, lambda: True)
        self.assertEqual(result["summary"]["completed"], 4)
        self.assertEqual(result["summary"]["errors"], 4)
        self.assertEqual(result["summary"]["requests_completed"], 1)
        self.assertEqual(result["summary"]["request_errors"], 1)
        self.assertIsNotNone(result["error"])

    def test_wrong_model_identity_is_not_counted_as_completed(self):
        self.response_model_name = "other_model"
        result = triton.run_experiment(8, 8, lambda: True)
        self.assertEqual(result["summary"]["completed"], 0)
        self.assertEqual(result["summary"]["errors"], 8)

    def test_wrong_model_version_is_not_counted_as_completed(self):
        self.response_model_version = "2"
        result = triton.run_experiment(8, 8, lambda: True)
        self.assertEqual(result["summary"]["completed"], 0)
        self.assertEqual(result["summary"]["errors"], 8)

    def test_boolean_or_noninteger_shape_is_not_counted_as_completed(self):
        for shape in ([True, 4], [1.0, 4], [1, True], [1, "4"]):
            with self.subTest(shape=shape):
                self.response_shape = shape
                result = triton.run_experiment(8, 1, lambda: True)
                self.assertEqual(result["summary"]["completed"], 0)
                self.assertEqual(result["summary"]["errors"], 8)
        self.response_shape = None

    def test_nonfinite_or_boolean_output_data_is_not_counted_as_completed(self):
        for data in ([2.0, 4.0, float("nan"), 8.0], [2.0, 4.0, float("inf"), 8.0],
                     [2.0, 4.0, True, 8.0], [2.0, 4.0, 6.0], ["2.0", 4.0, 6.0, 8.0]):
            with self.subTest(data=data):
                self.response_data = data
                result = triton.run_experiment(8, 8, lambda: True)
                self.assertEqual(result["summary"]["completed"], 0)
                self.assertEqual(result["summary"]["errors"], 8)
        self.response_data = None

    def test_stats_counter_validation_rejects_malformed_or_overflow_values(self):
        for count in (True, -1, 2**63, "01", "1.0", None):
            with self.subTest(count=count):
                with self.assertRaises(ValueError):
                    triton._counter(count)
        self.assertEqual(triton._counter("9223372036854775807"), 2**63 - 1)

    def test_observe_exposes_only_sanitized_identity_and_counters(self):
        result = triton.observe()
        self.assertEqual(result["model"], {"name": "lab_double", "version": "1"})
        self.assertTrue(result["ready"])
        self.assertEqual(result["stats"], {"success": 0, "inference_count": 0, "execution_count": 0})
        self.assertNotIn("url", result)


if __name__ == "__main__":
    unittest.main()
