"""Security contracts for the optional console; no kubectl or live provider."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class OperatorManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.objects = list(yaml.safe_load_all((ROOT / "k8s/operator/operator.yaml").read_text()))

    def test_observer_has_only_namespaced_pod_list(self):
        role = next(o for o in self.objects if o["kind"] == "Role")
        self.assertEqual(role["rules"], [{"apiGroups": [""], "resources": ["pods"], "verbs": ["list"]}])
        self.assertFalse(any(o["kind"] in {"ClusterRole", "ClusterRoleBinding", "Ingress"} for o in self.objects))
        service = next(o for o in self.objects if o["kind"] == "Service")
        self.assertEqual(service["spec"]["type"], "ClusterIP")

    def test_default_actions_closed_and_one_nonroot_process(self):
        deployment = next(o for o in self.objects if o["kind"] == "Deployment")
        self.assertEqual(deployment["spec"]["replicas"], 1)
        self.assertEqual(deployment["spec"]["strategy"]["type"], "Recreate")
        pod = deployment["spec"]["template"]["spec"]
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertTrue(pod["securityContext"]["runAsNonRoot"])
        container = pod["containers"][0]
        env = {v["name"]: v["value"] for v in container["env"]}
        self.assertEqual(env["LAB_ACTIONS_ENABLED"], "false")
        self.assertEqual(env["LAB_EXPIRES_AT"], "0")
        self.assertFalse(container["securityContext"]["allowPrivilegeEscalation"])
        self.assertTrue(container["securityContext"]["readOnlyRootFilesystem"])
        self.assertEqual(container["securityContext"]["capabilities"]["drop"], ["ALL"])

    def test_no_broad_ingress_policy_selects_console(self):
        base = yaml.safe_load((ROOT / "k8s/base/network.yaml").read_text())
        expressions = base["spec"]["podSelector"]["matchExpressions"]
        self.assertIn({"key": "app", "operator": "NotIn", "values": ["lab-operator"]}, expressions)
        policy = yaml.safe_load((ROOT / "k8s/operator/network.yaml").read_text())
        self.assertEqual(policy["spec"]["ingress"], [])
        egress = policy["spec"]["egress"]
        self.assertFalse(any(rule.get("to") == [] or "to" not in rule for rule in egress))
        self.assertNotIn("0.0.0.0/0", str(egress))


if __name__ == "__main__":
    unittest.main()
