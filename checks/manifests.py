"""Render both overlays and check the lab's capacity and exposure contract."""
import json
import subprocess
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
for overlay, replicas in (("base", 1), ("two-nodes", 2)):
    text = subprocess.check_output(["kubectl", "kustomize", str(ROOT / "k8s" / overlay)], text=True)
    objects = list(yaml.safe_load_all(text))
    for obj in objects:
        if obj["kind"] == "Service":
            assert obj["spec"].get("type", "ClusterIP") == "ClusterIP"
    model = next(o for o in objects if o["kind"] == "StatefulSet")
    assert model["spec"]["replicas"] == replicas
    assert "requiredDuringSchedulingIgnoredDuringExecution" in model["spec"]["template"]["spec"]["affinity"]["podAntiAffinity"]
    ray = next(o for o in objects if o["kind"] == "RayService")
    spec = ray["spec"]["rayClusterConfig"]
    assert spec["authOptions"]["mode"] == "token"
    assert spec["enableInTreeAutoscaling"] is False
    assert spec["headGroupSpec"]["serviceType"] == "ClusterIP"
    assert spec["workerGroupSpecs"][0]["replicas"] == replicas
    serve = yaml.safe_load(ray["spec"]["serveConfigV2"])
    assert serve["http_options"]["request_timeout_s"] == 65
    assert serve["applications"][0]["deployments"][0]["num_replicas"] == replicas
    assert not any("nvidia.com/gpu" in json.dumps(o) for o in objects)
    print(f"{overlay}: {len(objects)} resources; {replicas} model and Serve replica(s); private Services")
