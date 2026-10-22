"""Pulumi resource contract tests: no provider plugin, credentials or live API."""
import os
import runpy
import time
import unittest
from pathlib import Path
import pulumi
from pulumi.runtime import Mocks, MockResourceArgs, MockCallArgs

ROOT = Path(__file__).resolve().parents[1]
EXPIRY = int(time.time()) + 7200
RESOURCES = []

class FakeCloud(Mocks):
    def new_resource(self, args: MockResourceArgs):
        RESOURCES.append(args)
        state = dict(args.inputs)
        if args.typ == "pulumi:pulumi:StackReference":
            state["outputs"] = {"projectId": "sample-project", "zone": "us-central1-a",
                "networkId": "network", "subnetId": "subnet", "nodeServiceAccount": "node@example.invalid"}
        state.setdefault("email", "test@example.invalid")
        state.setdefault("uri", "https://expiry.example.run.app")
        return args.name + "-id", state
    def call(self, args: MockCallArgs):
        return args.args

pulumi.runtime.set_mocks(FakeCloud(), project="inference-lab-session", stack="test", preview=False)
pulumi.runtime.set_all_config({"lab:projectId": "sample-project", "lab:zone": "us-central1-a",
    "lab:runId": "abcdef123456", "lab:expiresAt": str(EXPIRY), "lab:nodeCount": "2",
    "lab:foundationStack": "org/inference-lab-foundation/test", "lab:enableExpiry": "true",
    "lab:expiryImage": "us-central1-docker.pkg.dev/sample-project/inference-lab/expiry@sha256:" + "a" * 64})

class Infrastructure(unittest.TestCase):
    @pulumi.runtime.test
    def test_cpu_session_and_authenticated_expiry(self):
        session = runpy.run_path(str(ROOT / "infra/session/__main__.py"))
        foundation = runpy.run_path(str(ROOT / "infra/foundation/__main__.py"))
        def verify(_):
            cluster = next(r.inputs for r in RESOURCES if r.typ == "gcp:container/cluster:Cluster")
            self.assertEqual(cluster["location"], "us-central1-a")
            self.assertNotIn("nodeLocations", cluster)
            self.assertNotIn("initialNodeCount", cluster)
            pool = cluster["nodePools"][0]
            self.assertEqual(pool["nodeCount"], 2)
            self.assertEqual(pool["upgradeSettings"]["maxSurge"], 0)
            self.assertNotIn("autoscaling", pool)
            self.assertEqual(pool["nodeConfig"]["machineType"], "n2-standard-4")
            self.assertNotIn("guestAccelerators", pool["nodeConfig"])
            self.assertFalse(cluster["controlPlaneEndpointsConfig"]["ipEndpointsConfig"]["enabled"])
            self.assertEqual(cluster["resourceLabels"]["lab-run"], "abcdef123456")
            iam = [r.inputs for r in RESOURCES if "IamMember" in r.typ]
            self.assertFalse(any(v.get("member") in ("allUsers", "allAuthenticatedUsers") for v in iam))
            queue = next(r.inputs for r in RESOURCES if r.typ == "gcp:cloudtasks/queue:Queue")
            self.assertEqual(queue["retryConfig"]["maxRetryDuration"], "86400s")
            self.assertEqual(queue["retryConfig"]["maxAttempts"], 100)
            self.assertFalse(any("RouterNat" in r.typ or "Firewall" in r.typ for r in RESOURCES))
            bucket = next(r.inputs for r in RESOURCES if r.typ == "gcp:storage/bucket:Bucket")
            self.assertEqual(bucket["publicAccessPrevention"], "enforced")
            self.assertTrue(bucket["uniformBucketLevelAccess"])
            self.assertEqual(bucket["lifecycleRules"][0]["condition"]["age"], 1)
            build_grants = [r.inputs for r in RESOURCES
                            if r.inputs.get("member") == "serviceAccount:test@example.invalid"]
            self.assertFalse(any(v.get("role") in ("roles/editor", "roles/owner") for v in build_grants))
        return pulumi.Output.all(session["cluster"].urn, foundation["queue"].urn,
                                 foundation["service"].urn).apply(verify)

if __name__ == "__main__":
    unittest.main()
