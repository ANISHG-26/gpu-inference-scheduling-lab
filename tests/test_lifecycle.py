from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from inference_lab.lifecycle import CloudTasks, LabConfig, LabController, LabError, Pulumi, required_labels, write_exclusive_json


FOUNDATION = {
    "projectId": "private-project", "zone": "northamerica-northeast1-a",
    "networkId": "network", "subnetId": "subnet", "nodeServiceAccount": "nodes@example.iam.gserviceaccount.com",
    "expiryUrl": "https://expiry.example/expire", "taskQueueId": "expiry-queue",
    "taskInvokerServiceAccount": "invoker@example.iam.gserviceaccount.com",
}


class FakePulumi:
    def __init__(self, events: list[str], session_outputs: dict[str, Any] | None = None):
        self.events = events
        self.session_outputs = session_outputs
        self.timeout = 20 * 60

    def existing_outputs(self, stack: str) -> dict[str, Any] | None:
        self.events.append("inspect-session")
        return self.session_outputs

    def outputs(self, stack: str) -> dict[str, Any]:
        self.events.append(f"outputs:{stack}")
        return FOUNDATION if stack == "foundation" else (self.session_outputs or {})

    def config_set(self, stack: str, key: str, value: str) -> None:
        self.events.append(f"config:{key}")

    def up(self, stack: str) -> None:
        self.events.append("up")
        self.session_outputs = {"projectId": "private-project", "zone": "northamerica-northeast1-a",
                                "clusterName": "inference-lab-012345abcdef", "runId": "012345abcdef",
                                "expiresAt": 1_900_000_000}

    def destroy(self, stack: str) -> None:
        self.events.append(f"destroy:{stack}")

    def refresh(self, stack: str) -> None:
        self.events.append(f"refresh:{stack}")


class FakeTasks:
    def __init__(self, events: list[str]):
        self.events = events

    def create_expiry_task(self, project_id: str, location: str, queue_id: str,
                           url: str, invoker: str, payload: dict[str, Any],
                           schedule_at: int, task_id: str) -> str:
        self.events.append("task")
        self.assertions = (location, queue_id, payload, schedule_at, task_id)
        return f"projects/{project_id}/locations/{location}/queues/{queue_id}/tasks/{task_id}"


class FakeGke:
    def __init__(self, labels: dict[str, str]):
        self.cluster_labels = labels

    def labels(self, project_id: str, zone: str, cluster_name: str) -> dict[str, str]:
        self.request = (project_id, zone, cluster_name)
        return self.cluster_labels

    def labels_or_absent(self, project_id: str, zone: str, cluster_name: str) -> dict[str, str] | None:
        self.request = (project_id, zone, cluster_name)
        return self.cluster_labels


class LabConfigTests(unittest.TestCase):
    def test_rejects_ttl_and_node_count_outside_safe_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            base = {"project_id": "p", "zone": "z", "foundation_stack": "f", "session_stack": "s",
                    "ttl_minutes": 29, "node_count": 1}
            path.write_text(json.dumps(base), encoding="utf-8")
            with self.assertRaisesRegex(LabError, "ttl_minutes"):
                LabConfig.load(path)
            base.update(ttl_minutes=30, node_count=3)
            path.write_text(json.dumps(base), encoding="utf-8")
            with self.assertRaisesRegex(LabError, "node_count"):
                LabConfig.load(path)

    def test_rejects_project_identifier_that_starts_with_option_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            path.write_text(json.dumps({"project_id": "--project", "zone": "zone-a",
                                        "foundation_stack": "foundation", "session_stack": "session",
                                        "ttl_minutes": 30, "node_count": 1}), encoding="utf-8")
            with self.assertRaisesRegex(LabError, "project_id"):
                LabConfig.load(path)

    def test_pulumi_argv_is_a_list_and_timeout_is_bounded(self) -> None:
        seen: list[Any] = []

        def runner(argv: list[str], **kwargs: Any) -> Any:
            seen.append((argv, kwargs))
            return type("Result", (), {"returncode": 0, "stdout": "{}", "stderr": ""})()

        cli = Pulumi(Path("."), timeout=99 * 60, runner=runner)
        cli.outputs("org/private stack")
        self.assertEqual(seen[0][0], ["pulumi", "stack", "output", "--json", "--stack", "org/private stack"])
        self.assertEqual(seen[0][1]["timeout"], 20 * 60)
        self.assertFalse(seen[0][1].get("shell", False))

    def test_pulumi_failure_hides_command_arguments_and_provider_output(self) -> None:
        def runner(argv: list[str], **kwargs: Any) -> Any:
            return type("Result", (), {"returncode": 1, "stdout": "", "stderr": "private-account@example.com"})()

        cli = Pulumi(Path("."), runner=runner)
        with self.assertRaises(LabError) as caught:
            cli.run("up", "--stack", "private-project/secret")
        self.assertNotIn("private-account@example.com", str(caught.exception))
        self.assertNotIn("private-project", str(caught.exception))


class LifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / ".lab").mkdir()
        (self.root / ".lab" / "config.json").write_text(json.dumps({
            "project_id": "private-project", "zone": "northamerica-northeast1-a",
            "foundation_stack": "foundation", "session_stack": "session",
            "ttl_minutes": 30, "node_count": 1,
        }), encoding="utf-8")
        self.events: list[str] = []
        self.pulumi = FakePulumi(self.events)
        self.tasks = FakeTasks(self.events)
        self.controller = LabController(self.root, pulumi=self.pulumi, task_client=self.tasks,
                                        clock=lambda: 1_899_998_200,
                                        run_id_factory=lambda: "012345abcdef")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_registers_expiry_before_up_and_keeps_run_record(self) -> None:
        result = self.controller.start()
        self.assertLess(self.events.index("task"), self.events.index("up"))
        self.assertEqual(self.tasks.assertions[0], "northamerica-northeast1")
        self.assertEqual(result["cluster_name"], "inference-lab-012345abcdef")
        record_path = self.root / ".lab" / "sessions" / "012345abcdef.json"
        self.assertEqual(json.loads(record_path.read_text(encoding="utf-8"))["expires_at"], 1_900_000_000)
        with self.assertRaises(FileExistsError):
            write_exclusive_json(record_path, {"run_id": "overwrite"})

    def test_plan_is_local_and_does_not_read_foundation_outputs(self) -> None:
        class NoCloudPulumi(FakePulumi):
            def outputs(self, stack: str) -> dict[str, Any]:
                raise AssertionError("plan must not inspect Pulumi state")

        controller = LabController(self.root, pulumi=NoCloudPulumi(self.events),
                                   clock=lambda: 1_899_998_200)
        plan = controller.plan()
        self.assertEqual(plan["node_count"], 1)
        self.assertEqual(plan["ttl_minutes"], 30)

    def test_pulumi_default_working_directories_are_split_by_stack(self) -> None:
        from inference_lab.lifecycle import Pulumi

        controller = LabController(self.root, pulumi_factory=lambda cwd: Pulumi(cwd))
        self.assertEqual(controller.pulumi.cwd, self.root / "infra" / "session")
        self.assertEqual(controller.foundation_pulumi.cwd, self.root / "infra" / "foundation")

    def test_existing_stack_run_blocks_new_task_and_up(self) -> None:
        self.pulumi.session_outputs = {"runId": "abcdef012345"}
        with self.assertRaisesRegex(LabError, "already exists"):
            self.controller.start()
        self.assertNotIn("task", self.events)
        self.assertNotIn("up", self.events)

    def test_task_registration_failure_keeps_record_and_never_runs_pulumi(self) -> None:
        def fail(*args: Any, **kwargs: Any) -> str:
            self.events.append("task-failed")
            raise LabError("Cloud Tasks registration failed")

        self.tasks.create_expiry_task = fail  # type: ignore[method-assign]
        with self.assertRaisesRegex(LabError, "Cloud Tasks"):
            self.controller.start()
        self.assertTrue((self.root / ".lab" / "sessions" / "012345abcdef.json").exists())
        self.assertNotIn("up", self.events)

    def test_stop_refuses_mismatched_live_labels_before_destroy(self) -> None:
        record = {"project_id": "private-project", "zone": "northamerica-northeast1-a",
                  "run_id": "012345abcdef", "cluster_name": "inference-lab-012345abcdef",
                  "expires_at": 1_900_000_000}
        write_exclusive_json(self.root / ".lab" / "sessions" / "012345abcdef.json", record)
        self.pulumi.session_outputs = {"projectId": record["project_id"], "zone": record["zone"],
                                       "clusterName": record["cluster_name"], "runId": record["run_id"],
                                       "expiresAt": record["expires_at"]}
        self.controller.gke = FakeGke(required_labels(record["run_id"], record["expires_at"]) | {"lab-run": "foreign"})
        with self.assertRaisesRegex(LabError, "labels"):
            self.controller.stop()
        self.assertFalse(any(event.startswith("destroy:") for event in self.events))

    def test_stop_destroys_only_session_stack_after_live_ownership_check(self) -> None:
        record = {"project_id": "private-project", "zone": "northamerica-northeast1-a",
                  "run_id": "012345abcdef", "cluster_name": "inference-lab-012345abcdef",
                  "expires_at": 1_900_000_000}
        write_exclusive_json(self.root / ".lab" / "sessions" / "012345abcdef.json", record)
        self.pulumi.session_outputs = {"projectId": record["project_id"], "zone": record["zone"],
                                       "clusterName": record["cluster_name"], "runId": record["run_id"],
                                       "expiresAt": record["expires_at"]}
        self.controller.gke = FakeGke(required_labels(record["run_id"], record["expires_at"]))
        self.assertEqual(self.controller.stop()["status"], "stopped")
        self.assertIn("destroy:session", self.events)
        self.assertNotIn("destroy:foundation", self.events)

    def test_stop_refreshes_before_destroy_when_expiry_already_removed_cluster(self) -> None:
        record = {"project_id": "private-project", "zone": "northamerica-northeast1-a",
                  "run_id": "012345abcdef", "cluster_name": "inference-lab-012345abcdef",
                  "expires_at": 1_900_000_000}
        write_exclusive_json(self.root / ".lab" / "sessions" / "012345abcdef.json", record)
        self.pulumi.session_outputs = {"projectId": record["project_id"], "zone": record["zone"],
                                       "clusterName": record["cluster_name"], "runId": record["run_id"],
                                       "expiresAt": record["expires_at"]}
        self.controller.gke = FakeGke(None)  # type: ignore[arg-type]
        self.controller.stop()
        self.assertLess(self.events.index("refresh:session"), self.events.index("destroy:session"))

    def test_stop_is_idempotent_after_stack_outputs_are_gone(self) -> None:
        record = {"project_id": "private-project", "zone": "northamerica-northeast1-a",
                  "run_id": "012345abcdef", "cluster_name": "inference-lab-012345abcdef",
                  "expires_at": 1_900_000_000}
        write_exclusive_json(self.root / ".lab" / "sessions" / "012345abcdef.json", record)
        self.controller.stopped_dir.mkdir(parents=True)
        (self.controller.stopped_dir / "012345abcdef.marker").write_text("012345abcdef\n", encoding="ascii")
        self.pulumi.session_outputs = {}
        result = self.controller.stop()
        self.assertEqual(result["status"], "stopped")
        self.assertNotIn("destroy:session", self.events)

    def test_refuses_stack_and_project_values_that_could_be_cli_options(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            config = {"project_id": "private-project", "zone": "northamerica-northeast1-a",
                      "foundation_stack": "foundation", "session_stack": "--destroy",
                      "ttl_minutes": 30, "node_count": 1}
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(LabError, "session_stack"):
                LabConfig.load(path)

    def test_fails_if_ttl_elapsed_during_successful_pulumi_up(self) -> None:
        times = iter([1_899_998_200, 1_899_998_200, 1_900_000_000])
        controller = LabController(self.root, pulumi=self.pulumi, task_client=self.tasks,
                                   clock=lambda: next(times), run_id_factory=lambda: "012345abcdef")
        with self.assertRaisesRegex(LabError, "TTL expired"):
            controller.start()
        self.assertIn("up", self.events)
        self.assertTrue((self.root / ".lab" / "sessions" / "012345abcdef.json").exists())


class CloudTaskTests(unittest.TestCase):
    class FakeResponse:
        def __init__(self, status_code: int, value: dict[str, Any]):
            self.status_code, self.value = status_code, value
            self.ok = 200 <= status_code < 300

        def json(self) -> dict[str, Any]:
            return self.value

    class FakeHttp:
        def __init__(self, responses: list["CloudTaskTests.FakeResponse"]):
            self.responses = list(responses)
            self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

        def post(self, url: str, json: dict[str, Any], timeout: int) -> "CloudTaskTests.FakeResponse":
            self.calls.append(("POST", url, json))
            return self.responses.pop(0)

        def get(self, url: str, timeout: int) -> "CloudTaskTests.FakeResponse":
            self.calls.append(("GET", url, None))
            return self.responses.pop(0)

    def create(self, client: CloudTasks) -> str:
        return client.create_expiry_task("private-project", "northamerica-northeast1", "queue",
                                         "https://expiry.example/expire", "invoker@example.com",
                                         {"project_id": "private-project", "run_id": "012345abcdef"},
                                         1_900_000_000, "expire-012345abcdef")

    def test_duplicate_task_is_reused_only_after_request_match(self) -> None:
        desired_name = "projects/private-project/locations/northamerica-northeast1/queues/queue/tasks/expire-012345abcdef"
        task = {"name": desired_name, "scheduleTime": "2030-03-17T17:46:40Z",
                "httpRequest": {"httpMethod": "POST", "url": "https://expiry.example/expire", "body": "e30=",
                                "oidcToken": {"serviceAccountEmail": "invoker@example.com",
                                              "audience": "https://expiry.example"}}}
        # The body is verified against the exact request, including the OIDC audience.
        import base64
        task["httpRequest"]["body"] = base64.b64encode(
            json.dumps({"project_id": "private-project", "run_id": "012345abcdef"}).encode()
        ).decode()
        http = self.FakeHttp([self.FakeResponse(409, {}), self.FakeResponse(200, task)])
        client = CloudTasks(http_session=http)
        self.assertEqual(self.create(client), desired_name)
        self.assertEqual([call[0] for call in http.calls], ["POST", "GET"])
        self.assertTrue(http.calls[1][1].endswith("?responseView=FULL"))

    def test_duplicate_task_with_foreign_payload_is_rejected(self) -> None:
        task = {"name": "projects/private-project/locations/northamerica-northeast1/queues/queue/tasks/expire-012345abcdef",
                "scheduleTime": "2030-03-17T17:46:40Z",
                "httpRequest": {"httpMethod": "POST", "url": "https://expiry.example/expire", "body": "Zm9yZWlnbg==",
                                "oidcToken": {"serviceAccountEmail": "invoker@example.com",
                                              "audience": "https://expiry.example/expire"}}}
        http = self.FakeHttp([self.FakeResponse(409, {}), self.FakeResponse(200, task)])
        with self.assertRaisesRegex(LabError, "existing Cloud Task"):
            self.create(CloudTasks(http_session=http))

    def test_successful_task_creation_must_return_requested_name(self) -> None:
        http = self.FakeHttp([self.FakeResponse(200, {"name": "wrong/task"})])
        with self.assertRaisesRegex(LabError, "task name"):
            self.create(CloudTasks(http_session=http))

    def test_registration_uses_cloud_tasks_create_request_envelope(self) -> None:
        name = "projects/private-project/locations/northamerica-northeast1/queues/queue/tasks/expire-012345abcdef"
        http = self.FakeHttp([self.FakeResponse(200, {"name": name})])
        self.create(CloudTasks(http_session=http))
        payload = http.calls[0][2]
        self.assertEqual(set(payload), {"task"})
        self.assertEqual(payload["task"]["name"], name)
        self.assertEqual(payload["task"]["httpRequest"]["oidcToken"]["audience"], "https://expiry.example")


if __name__ == "__main__":
    unittest.main()
