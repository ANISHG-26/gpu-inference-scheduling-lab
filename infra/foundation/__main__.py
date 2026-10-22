"""Retained foundation. Deliberately does not enable APIs or billing."""
import re
import pulumi
import pulumi_gcp as gcp

cfg = pulumi.Config("lab")
project = cfg.require("projectId")
zone = cfg.require("zone")
if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", project):
    raise ValueError("Use an explicit Google Cloud project ID")
if not re.fullmatch(r"[a-z]+-[a-z]+[0-9]-[a-z]", zone):
    raise ValueError("Use an explicit zonal location")
region = zone.rsplit("-", 1)[0]
provider = gcp.Provider("lab", project=project, region=region, zone=zone)
opts = pulumi.ResourceOptions(provider=provider)
network = gcp.compute.Network("lab", name="inference-lab", auto_create_subnetworks=False, opts=opts)
subnet = gcp.compute.Subnetwork("lab", name="inference-lab", region=region,
    network=network.id, ip_cidr_range="10.92.0.0/24", private_ip_google_access=True,
    secondary_ip_ranges=[{"range_name": "pods", "ip_cidr_range": "10.93.0.0/20"},
                         {"range_name": "services", "ip_cidr_range": "10.94.0.0/24"}], opts=opts)
registry = gcp.artifactregistry.Repository("lab", repository_id="inference-lab", location=region,
    format="DOCKER", description="Lab images; retained storage has a cost", opts=opts)
node = gcp.serviceaccount.Account("node", account_id="inference-lab-node", opts=opts)
expiry = gcp.serviceaccount.Account("expiry", account_id="inference-lab-expiry", opts=opts)
invoker = gcp.serviceaccount.Account("task-invoker", account_id="inference-lab-task", opts=opts)
gcp.projects.IAMMember("node-runtime", project=project, role="roles/container.defaultNodeServiceAccount",
    member=node.email.apply(lambda e: "serviceAccount:" + e), opts=opts)
gcp.artifactregistry.RepositoryIamMember("node-pull", project=project, location=region,
    repository=registry.name, role="roles/artifactregistry.reader",
    member=node.email.apply(lambda e: "serviceAccount:" + e), opts=opts)
role = gcp.projects.IAMCustomRole("expiry-role", project=project, role_id="inferenceLabExpiry",
    title="Read and delete lab GKE clusters", permissions=["container.clusters.get", "container.clusters.delete",
    "container.operations.get"], opts=opts)
gcp.projects.IAMMember("expiry-runtime", project=project, role=role.name,
    member=expiry.email.apply(lambda e: "serviceAccount:" + e), opts=opts)
queue = gcp.cloudtasks.Queue("expiry", name="inference-lab-expiry", location=region,
    rate_limits={"max_concurrent_dispatches": 1, "max_dispatches_per_second": 1},
    retry_config={"max_attempts": 100, "max_retry_duration": "86400s", "min_backoff": "30s",
                  "max_backoff": "300s", "max_doublings": 4}, opts=opts)

# Bootstrap network/registry first. Deploy the expiry service only after its image is built.
expiry_url = pulumi.Output.from_input("")
if cfg.get_bool("enableExpiry"):
    image = cfg.require("expiryImage")
    expected_prefix = f"{region}-docker.pkg.dev/{project}/inference-lab/expiry@sha256:"
    if not image.startswith(expected_prefix) or not re.fullmatch(r"[0-9a-f]{64}", image[len(expected_prefix):]):
        raise ValueError("expiryImage must be a digest in this foundation's registry")
    service = gcp.cloudrunv2.Service("expiry", name="inference-lab-expiry", location=region,
        deletion_protection=False, ingress="INGRESS_TRAFFIC_ALL",
        template={"service_account": expiry.email, "timeout": "120s",
                  "scaling": {"min_instance_count": 0, "max_instance_count": 1},
                  "containers": [{"image": image, "ports": {"container_port": 8080},
                    "envs": [{"name": "LAB_PROJECT_ID", "value": project}],
                    "resources": {"limits": {"cpu": "1", "memory": "256Mi"}, "cpu_idle": True}}]}, opts=opts)
    gcp.cloudrunv2.ServiceIamMember("invoke-expiry", project=project, location=region,
        name=service.name, role="roles/run.invoker",
        member=invoker.email.apply(lambda e: "serviceAccount:" + e), opts=opts)
    expiry_url = service.uri.apply(lambda u: u + "/expire")

for key, value in {"projectId": project, "zone": zone, "networkId": network.id,
    "subnetId": subnet.id, "nodeServiceAccount": node.email, "expiryUrl": expiry_url,
    "taskQueueId": queue.name, "taskInvokerServiceAccount": invoker.email,
    "registry": registry.id}.items():
    pulumi.export(key, value)
