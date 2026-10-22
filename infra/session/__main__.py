"""Only the short-lived GKE cluster belongs to the session state."""
import re
import time
import pulumi
import pulumi_gcp as gcp

cfg = pulumi.Config("lab")
project, zone, run_id = cfg.require("projectId"), cfg.require("zone"), cfg.require("runId")
expires = cfg.require_int("expiresAt")
nodes = cfg.require_int("nodeCount")
if not re.fullmatch(r"[0-9a-f]{12}", run_id) or nodes not in (1, 2):
    raise ValueError("Session must have a unique run ID and one or two fixed nodes")
if expires <= int(time.time()) or expires > int(time.time()) + 240 * 60:
    raise ValueError("Session expiry must be in the next four hours")
foundation = pulumi.StackReference(cfg.require("foundationStack"))
def match(values):
    if values != [project, zone]:
        raise ValueError("Foundation and session project/location must match")
    return True
verified = pulumi.Output.all(foundation.require_output("projectId"), foundation.require_output("zone")).apply(match)
provider = gcp.Provider("session", project=project, zone=zone, region=zone.rsplit("-", 1)[0])
cluster_name = "inference-lab-" + run_id
cluster = gcp.container.Cluster("session", name=cluster_name, project=project, location=zone,
    deletion_protection=False,
    network=pulumi.Output.all(foundation.require_output("networkId"), verified).apply(lambda v: v[0]),
    subnetwork=foundation.require_output("subnetId"),
    resource_labels={"managed-by": "inference-lab", "lab-run": run_id, "lab-expiry": str(expires)},
    node_locations=[zone], networking_mode="VPC_NATIVE", datapath_provider="ADVANCED_DATAPATH",
    ip_allocation_policy={"cluster_secondary_range_name": "pods", "services_secondary_range_name": "services"},
    release_channel={"channel": "REGULAR"},
    control_plane_endpoints_config={"dns_endpoint_config": {"allow_external_traffic": True},
                                    "ip_endpoints_config": {"enabled": False}},
    # Public node egress avoids a retained Cloud NAT. No application LoadBalancer or inbound firewall.
    node_pools=[{"name": "cpu", "node_count": nodes,
      "upgrade_settings": {"max_surge": 0, "max_unavailable": 1},
      "node_config": {"machine_type": "n2-standard-4", "min_cpu_platform": "Intel Cascade Lake",
        "disk_size_gb": 30, "disk_type": "pd-standard", "image_type": "COS_CONTAINERD",
        "service_account": foundation.require_output("nodeServiceAccount"),
        "oauth_scopes": ["https://www.googleapis.com/auth/cloud-platform"],
        "metadata": {"disable-legacy-endpoints": "true"},
        "shielded_instance_config": {"enable_secure_boot": True, "enable_integrity_monitoring": True}}}],
    logging_config={"enable_components": ["SYSTEM_COMPONENTS"]},
    monitoring_config={"enable_components": ["SYSTEM_COMPONENTS"]},
    opts=pulumi.ResourceOptions(provider=provider, depends_on=[foundation]))
for key, value in {"projectId": project, "zone": zone, "clusterName": cluster_name,
                   "runId": run_id, "expiresAt": expires, "nodeCount": nodes}.items():
    pulumi.export(key, value)
