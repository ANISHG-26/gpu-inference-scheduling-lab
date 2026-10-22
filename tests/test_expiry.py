from __future__ import annotations

import unittest
from typing import Any

from inference_lab.expiry import expected_labels, process_expiry


PAYLOAD = {"project_id": "private-project", "zone": "northamerica-northeast1-a",
           "run_id": "012345abcdef", "cluster_name": "inference-lab-012345abcdef", "expires_at": 1000}


class Response:
    def __init__(self, status_code: int, value: dict[str, Any] | None = None):
        self.status_code = status_code
        self.value = value or {}

    def json(self) -> dict[str, Any]:
        return self.value


class FakeSession:
    def __init__(self, gets: list[Response], delete: Response | None = None):
        self.gets = list(gets)
        self.delete_response = delete or Response(202)
        self.calls: list[str] = []

    def get(self, url: str, timeout: int) -> Response:
        self.calls.append("get")
        return self.gets.pop(0)

    def delete(self, url: str, timeout: int) -> Response:
        self.calls.append("delete")
        return self.delete_response


class ExpiryTests(unittest.TestCase):
    def test_early_expiry_retries_without_cloud_request(self) -> None:
        session = FakeSession([])
        status, _ = process_expiry(PAYLOAD, "private-project", session, now=lambda: 999)
        self.assertEqual(status, 503)
        self.assertEqual(session.calls, [])

    def test_missing_cluster_retries_until_grace_then_acknowledges(self) -> None:
        status, _ = process_expiry(PAYLOAD, "private-project", FakeSession([Response(404)]), now=lambda: 1001)
        self.assertEqual(status, 503)
        status, _ = process_expiry(PAYLOAD, "private-project", FakeSession([Response(404)]), now=lambda: 2801)
        self.assertEqual(status, 200)

    def test_rejects_foreign_labels_without_delete(self) -> None:
        session = FakeSession([Response(200, {"resourceLabels": expected_labels(PAYLOAD) | {"lab-run": "foreign"}})])
        status, _ = process_expiry(PAYLOAD, "private-project", session, now=lambda: 1001)
        self.assertEqual(status, 403)
        self.assertEqual(session.calls, ["get"])

    def test_accepts_additional_labels_when_required_ownership_labels_match(self) -> None:
        session = FakeSession([
            Response(200, {"resourceLabels": expected_labels(PAYLOAD) | {"pulumi-stack": "session"}}),
            Response(404),
        ])
        status, _ = process_expiry(PAYLOAD, "private-project", session, now=lambda: 1001)
        self.assertEqual(status, 200)

    def test_delete_returns_retry_until_gke_reports_verified_404(self) -> None:
        in_progress = FakeSession([
            Response(200, {"resourceLabels": expected_labels(PAYLOAD)}),
            Response(200, {"resourceLabels": expected_labels(PAYLOAD)}),
        ])
        status, _ = process_expiry(PAYLOAD, "private-project", in_progress, now=lambda: 1001)
        self.assertEqual(status, 503)
        completed = FakeSession([
            Response(200, {"resourceLabels": expected_labels(PAYLOAD)}),
            Response(404),
        ])
        status, _ = process_expiry(PAYLOAD, "private-project", completed, now=lambda: 1001)
        self.assertEqual(status, 200)
        self.assertEqual(completed.calls, ["get", "delete", "get"])

    def test_rejects_project_or_cluster_name_mismatch(self) -> None:
        session = FakeSession([])
        status, _ = process_expiry(PAYLOAD, "another-project", session, now=lambda: 1001)
        self.assertEqual(status, 400)
        bad = {**PAYLOAD, "cluster_name": "other-cluster"}
        status, _ = process_expiry(bad, "private-project", session, now=lambda: 1001)
        self.assertEqual(status, 400)
        self.assertEqual(session.calls, [])


if __name__ == "__main__":
    unittest.main()
