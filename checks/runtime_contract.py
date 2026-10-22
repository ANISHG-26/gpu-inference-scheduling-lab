"""Check Ray's real configuration schema without starting a cluster."""
from pathlib import Path
import subprocess
import yaml
from ray.serve.schema import ServeDeploySchema
from inference_lab.ray_app import app, InferenceAPI

root = Path(__file__).resolve().parents[1]
for overlay in ("base", "two-nodes"):
    objects = list(yaml.safe_load_all(subprocess.check_output(
        ["kubectl", "kustomize", str(root / "k8s" / overlay)], text=True)))
    ray = next(o for o in objects if o["kind"] == "RayService")
    ServeDeploySchema.model_validate(yaml.safe_load(ray["spec"]["serveConfigV2"]))
    print(f"{overlay}: Ray Serve schema accepted")
assert InferenceAPI.name == "InferenceAPI"
print("Ray application import accepted; no model or Ray cluster launched")
