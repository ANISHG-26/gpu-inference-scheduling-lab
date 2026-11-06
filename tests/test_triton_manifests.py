"""Rendered contracts for the gated lesson 04 Triton workload."""
from pathlib import Path
import subprocess
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
LESSON = ROOT / "lessons/04-triton-cpu-serving"


class TritonManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run(
            ["kubectl", "kustomize", str(LESSON)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        cls.objects = list(yaml.safe_load_all(result.stdout))
        cls.by_kind_name = {(o["kind"], o["metadata"]["name"]): o for o in cls.objects}

    def test_kustomization_renders_local_baseline_namespace_and_stable_model_configmap(self):
        namespace = self.by_kind_name[("Namespace", "inference-lab")]
        self.assertEqual(namespace["metadata"]["labels"]["pod-security.kubernetes.io/enforce"], "baseline")

        model = self.by_kind_name[("ConfigMap", "triton-model")]
        source = LESSON / "model-repository/lab_double"
        self.assertEqual(model["data"]["config.pbtxt"].replace("\r\n", "\n"),
                         (source / "config.pbtxt").read_text())
        self.assertEqual(model["data"]["model.py"].replace("\r\n", "\n"),
                         (source / "1/model.py").read_text())
        self.assertEqual(model["metadata"]["namespace"], "inference-lab")

    def test_single_cpu_statefulset_has_gated_nonroot_runtime_contract(self):
        workload = self.by_kind_name[("StatefulSet", "triton")]
        spec = workload["spec"]
        self.assertEqual(spec["replicas"], 1)
        self.assertEqual(spec["serviceName"], "triton")
        pod = spec["template"]["spec"]
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertFalse(pod["enableServiceLinks"])
        self.assertEqual(pod["securityContext"], {
            "runAsNonRoot": True,
            "runAsUser": 1000,
            "runAsGroup": 1000,
            "fsGroup": 1000,
            "seccompProfile": {"type": "RuntimeDefault"},
        })

        container, = pod["containers"]
        self.assertEqual(container["image"], "registry.invalid/nvidia/tritonserver:review-required")
        self.assertEqual(container["command"], ["/opt/tritonserver/bin/tritonserver"])
        self.assertEqual(container["args"], [
            "--model-repository=/models",
            "--model-control-mode=none",
            "--allow-gpu-metrics=false",
            "--allow-grpc=false",
            "--pinned-memory-pool-byte-size=0",
        ])
        security = container["securityContext"]
        self.assertFalse(security["allowPrivilegeEscalation"])
        self.assertTrue(security["readOnlyRootFilesystem"])
        self.assertEqual(security["capabilities"]["drop"], ["ALL"])
        self.assertEqual(container["resources"], {
            "requests": {"cpu": "1", "memory": "3Gi", "ephemeral-storage": "128Mi"},
            "limits": {"cpu": "2", "memory": "4Gi", "ephemeral-storage": "1Gi"},
        })
        mounts = {m["name"]: m for m in container["volumeMounts"]}
        self.assertTrue(mounts["model"]["readOnly"])
        self.assertEqual(mounts["model"]["mountPath"], "/models")
        self.assertEqual({n: mounts[n]["mountPath"] for n in ("tmp", "shm")}, {
            "tmp": "/tmp", "shm": "/dev/shm",
        })
        volumes = {v["name"]: v for v in pod["volumes"]}
        self.assertEqual(volumes["model"]["configMap"]["name"], "triton-model")
        self.assertEqual(volumes["model"]["configMap"]["items"], [
            {"key": "config.pbtxt", "path": "lab_double/config.pbtxt"},
            {"key": "model.py", "path": "lab_double/1/model.py"},
        ])
        self.assertEqual(volumes["tmp"]["emptyDir"]["sizeLimit"], "256Mi")
        self.assertEqual(volumes["shm"]["emptyDir"], {"medium": "Memory", "sizeLimit": "128Mi"})

    def test_only_http_clusterip_service_and_operator_ingress_are_exposed(self):
        services = [o for o in self.objects if o["kind"] == "Service"]
        self.assertEqual(len(services), 1)
        service = services[0]
        self.assertEqual(service["metadata"]["name"], "triton")
        self.assertEqual(service["spec"]["type"], "ClusterIP")
        self.assertEqual(service["spec"]["ports"], [{"name": "http", "port": 8000, "targetPort": "http", "protocol": "TCP"}])

        policy = self.by_kind_name[("NetworkPolicy", "triton")]["spec"]
        self.assertEqual(policy["podSelector"]["matchLabels"], {"app": "triton"})
        self.assertEqual(policy["policyTypes"], ["Ingress", "Egress"])
        self.assertEqual(policy["ingress"], [{
            "from": [{"podSelector": {"matchLabels": {"app": "lab-operator"}}}],
            "ports": [{"protocol": "TCP", "port": 8000}],
        }])
        self.assertEqual(policy["egress"], [])


if __name__ == "__main__":
    unittest.main()
