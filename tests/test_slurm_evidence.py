"""Offline structural checks; fixtures are not Slurm acceptance evidence."""

import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).parents[1] / "lessons" / "03-slurm-cpu-scheduling" / "evidence.py"
spec = importlib.util.spec_from_file_location("slurm_evidence", MODULE_PATH)
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)


def sample():
    jobs = [
        {"job_id": 101, "run_id": "run-a", "owner": "lesson-user", "lesson_id": "03",
         "cpus": 1, "time_limit_seconds": 60},
        {"job_id": 102, "run_id": "run-a", "owner": "lesson-user", "lesson_id": "03",
         "cpus": 1, "time_limit_seconds": 30},
        {"job_id": 103, "run_id": "run-a", "owner": "lesson-user", "lesson_id": "03",
         "cpus": 1, "time_limit_seconds": 30},
    ]
    def snap(at, stage, states, allocations):
        return {"observed_at": at, "stage": stage, "jobs": [
            {"job_id": j["job_id"], "state": states[i], "allocated_cpus": allocations[i]}
            for i, j in enumerate(jobs)]}
    return {"lesson_id": "03", "run_id": "run-a", "owner": "lesson-user", "source": "fixture",
            "provenance": {"source": "local fixture"}, "expires_at": 200,
            "jobs": jobs, "cancellation": {"job_id": 101, "run_id": "run-a", "owner": "lesson-user", "recorded_at": 105},
            "snapshots": [snap(101, "queued", ["RUNNING", "PENDING", "RUNNING"], [1, 0, 1]),
                          snap(110, "released", ["CANCELLED", "RUNNING", "RUNNING"], [0, 1, 1]),
                          snap(120, "finished", ["CANCELLED", "COMPLETED", "COMPLETED"], [0, 0, 0])]}


class SlurmEvidenceTests(unittest.TestCase):
    def test_unrepresentable_timestamp_is_rejected_as_invalid_evidence(self):
        value = sample()
        value["expires_at"] = 10 ** 400
        with self.assertRaises(ValueError):
            evidence.validate(value)

    def test_valid_structure_is_never_marked_measured(self):
        result = evidence.validate(sample())
        self.assertTrue(result["structurally_valid"])
        self.assertEqual(result["source"], "fixture")
        self.assertNotIn("measured", result)
        live = sample()
        live["source"] = "live"
        live["provenance"] = {"source": "authenticated adapter", "cluster_uid": "c1", "worker_uid": "w1", "collector": "a1"}
        self.assertNotIn("measured", evidence.validate(live))

    def test_rejects_bad_shapes_and_boundaries(self):
        cases = []
        x = sample(); x["jobs"][0]["job_id"] = True; cases.append(x)
        x = sample(); x["jobs"][1]["job_id"] = 101; cases.append(x)
        x = sample(); x["jobs"][0]["owner"] = "other"; cases.append(x)
        x = sample(); x["cancellation"]["owner"] = "other"; cases.append(x)
        x = sample(); x["cancellation"]["run_id"] = "other"; cases.append(x)
        x = sample(); x["cancellation"]["job_id"] = 999; cases.append(x)
        x = sample(); x["cancellation"]["job_id"] = 102; cases.append(x)
        x = sample(); x["snapshots"][0]["jobs"][0]["job_id"] = 999; cases.append(x)
        x = sample(); x["snapshots"][0]["jobs"][0]["job_id"] = 102; cases.append(x)
        x = sample(); x["source"] = "live"; cases.append(x)
        x = sample(); x["snapshots"][0]["observed_at"] = float("nan"); cases.append(x)
        x = sample(); x["jobs"][0]["cpus"] = 0; cases.append(x)
        x = sample(); x["jobs"][0]["time_limit_seconds"] = 61; cases.append(x)
        x = sample(); x["expires_at"] = float("inf"); cases.append(x)
        x = sample(); x["snapshots"][0]["jobs"][0]["allocated_cpus"] = 2; cases.append(x)
        x = sample(); x["snapshots"][0]["jobs"][1]["state"] = "RUNNING"; cases.append(x)
        x = sample(); x["snapshots"][1]["stage"] = "queued"; cases.append(x)
        x = sample(); x["snapshots"][1]["observed_at"] = 100; cases.append(x)
        x = sample(); x["cancellation"]["recorded_at"] = 100; cases.append(x)
        x = sample(); x["snapshots"][1]["jobs"].pop(); cases.append(x)
        x = sample(); x["snapshots"][2]["jobs"][2]["state"] = "RUNNING"; cases.append(x)
        x = sample(); x["snapshots"][2]["observed_at"] = 201; cases.append(x)
        x = sample(); x["snapshots"][2]["observed_at"] = 200; cases.append(x)
        x = sample(); x["source"] = "fixture"; x["provenance"] = {}; cases.append(x)
        x = sample(); del x["snapshots"]; cases.append(x)
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    evidence.validate(value)


if __name__ == "__main__":
    unittest.main()
