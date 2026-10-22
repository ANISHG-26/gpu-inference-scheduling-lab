# Operator runbook

These are activation instructions for the owner's next session. They have not been executed against GCP. Use Linux for container and model checks. Keep account-specific values, provider output and state private. No Terraform is required.

## Before spending credits

Confirm the intended project's billing account and current trial balance/expiry/eligibility. An open billing account alone does not establish trial entitlement. Google's [trial restrictions](https://docs.cloud.google.com/free/docs/free-cloud-features) prevent adding GPUs to VMs on an unupgraded trial; this CPU lab does not require a billing upgrade.

Review quotas for N2 CPUs (4 initially, 8 for the later two-node session), zonal capacity, standard persistent disks (30 GB/node), public addresses (one/node), GKE clusters and networking. Confirm `n2-standard-4` and Intel Cascade Lake minimum CPU availability in the selected zone. Test AVX512 flags and vLLM on the actual target. The pinned image exists, but has not been run here. The [CPU engine requirements](https://docs.vllm.ai/en/latest/getting_started/installation/cpu/) and model's memory demand must be checked together.

Write down the current full session estimate: GKE management fee after applicable credits, N2 nodes, boot disks, IPv4, image/model egress, logging, Artifact Registry storage, Cloud Run and Cloud Tasks. Multiply by the provisioning-plus-experiment window and include cleanup delay. No estimate or available-credit claim is supplied by this preparation. Set a budget alert, but do not treat alerts or credits as a hard spending cap.

Two GKE nodes are fixed in one zone; there is no cluster autoscaler or GPU. Pool upgrades use zero surge and one unavailable node. GKE repair/replacement and deletion are asynchronous, so the configured count is not a contractual cost ceiling. Nodes have public egress addresses to download images/weights without a retained Cloud NAT. There are no public workload Services or inbound rules added by this code. The Kubernetes control plane uses a DNS endpoint with IAM access; IP endpoints are disabled. This tradeoff needs owner review.

## One-time foundation activation

Install reviewed versions of Pulumi CLI, Python 3.12, gcloud, kubectl, Helm and Docker. Use authenticated private Pulumi state (Pulumi Cloud or an owner-managed private backend); do not commit state or stack config. `lab:*` is the explicit configuration namespace. The Python SDK pins are in each project's `requirements.txt`.

Review/enable the required APIs yourself: Compute, Container, Artifact Registry, Cloud Run, Cloud Tasks and IAM. API enablement and IAM bootstrap are deliberately outside these programs. Establish application default credentials for the selected project. Do not use Fleet state or its deployment identity by default.

Initialize a foundation stack from `infra/foundation`; set `lab:projectId`, `lab:zone`, and `lab:enableExpiry=false`. Run a Pulumi preview and review the network, subnet, registry, service accounts, custom expiry role and queue before `pulumi up`. Example commands below assume a fully qualified stack name substituted by the operator:

```sh
cd infra/foundation
pulumi stack init YOUR_ORG/inference-lab-foundation/dev
pulumi config set lab:projectId YOUR_PROJECT
pulumi config set lab:zone YOUR_ZONE
pulumi config set lab:enableExpiry false
pulumi preview
# Owner-approved activation only:
pulumi up
```

The expiry runtime has only cluster get/delete and operation get permissions. The node identity receives GKE default node runtime permissions and read access to this registry. The Cloud Tasks service agent needs its standard service-agent role to mint OIDC tokens; the operator creating tasks needs `cloudtasks.tasks.create/get/fullView` on the lab queue and `iam.serviceAccounts.actAs` on the task invoker. Review provisioning permissions separately; never give the expiry runtime broad project editor privileges.

Build `containers/expiry.Dockerfile`, publish it to this foundation's Artifact Registry, and record its digest. Set `lab:expiryImage` to `REGION-docker.pkg.dev/PROJECT/inference-lab/expiry@sha256:DIGEST`, then `lab:enableExpiry=true`. Preview/apply the foundation again. Only the task identity receives `roles/run.invoker`; no `allUsers` binding. Network ingress allows Cloud Tasks to reach Cloud Run, with IAM providing authentication. The task audience is the Cloud Run service origin; the request path is `/expire`.

Verify the expiry service's identity, queue retries, IAM and outputs before the first cluster. Test that unauthenticated requests are denied. An authenticated invalid payload must fail without deleting anything. Then prove a real short session expires and backing resources disappear before relying on unattended experiments. A successful mocked delete is insufficient.

## Start a disposable session

Initialize an **empty** session stack from `infra/session`, with the same private backend. Keep the foundation and session stack names distinct and fully qualified. Return to the repository root. Install the package with `.[cloud,checks,serve]`. Copy `config/lab.example.json` to ignored `.lab/config.json`, replace placeholders, and leave the initial node count at one. Default TTL is 120 minutes; allowed range is 30–240, starting before provisioning.

```sh
cd infra/session
pulumi stack init YOUR_ORG/inference-lab-session/dev
cd ../..
python -m inference_lab.lab plan
# After the owner has reviewed current cost/quota/IAM and activated expiry:
python -m inference_lab.lab start
python -m inference_lab.lab status
```

`plan` only validates local configuration and reports intended bounds; it is not a provider-backed cost or resource preview. During first activation, inspect the session program and a private Pulumi preview with a fresh short-lived run configuration before starting. The controller writes immutable private intent, registers the expiry task, sets session config and calls Pulumi. Do not bypass it with a direct session `pulumi up`, because that bypasses expiry registration.

Preserve `.lab/sessions` and private Pulumi state across operator machines. The local start lock prevents two starts in this checkout, not distributed coordination across arbitrary laptops. Operate this first version from one checkout/identity. If provisioning fails, retain the intent and task; inspect the exact cluster and stack privately. Do not clear locks/records to force another start. A failed apply without outputs requires operator recovery of that exact run; never guess another cluster name or destroy the foundation.

## Deploy the serving workload

Build `containers/ray.Dockerfile`, publish to the private foundation registry, scan/check it and record the digest. Replace both `registry.invalid/inference-lab/ray:review-required` entries using a private Kustomize overlay or a reviewed source change. A placeholder is intentional: the template must not pull an unreviewed custom image.

Get credentials for the recorded cluster using `gcloud container clusters get-credentials CLUSTER --zone ZONE --project PROJECT --dns-endpoint`. Verify `kubectl config current-context` and cluster identity before applying anything.

```sh
helm repo add kuberay https://ray-project.github.io/kuberay-helm/
helm repo update
helm show chart kuberay/kuberay-operator --version 1.7.1
kubectl apply -f k8s/base/namespace.yaml -n inference-lab
helm upgrade --install kuberay-operator kuberay/kuberay-operator \
  --version 1.7.1 --namespace kuberay-system --create-namespace \
  --values k8s/operator-values.yaml --wait --timeout 5m
kubectl apply -k YOUR_PRIVATE_RENDER_OVERLAY
kubectl -n inference-lab rollout status statefulset/vllm --timeout=15m
kubectl -n inference-lab get rayservices,pods,services -o wide
kubectl -n inference-lab port-forward service/inference-serve-svc 8000:8000
```

The operator values use the chart's namespace list and namespaced RBAC. Validate the downloaded chart and RayService CRD schema at activation; these manifests were rendered locally and their Serve configuration checked with Ray's SDK, not installed on Kubernetes. Keep port-forwards bound to localhost.

The vLLM pod runs non-root without extra Linux capabilities. `nobind` disables CPU thread affinity in this lab. If the image requires different permissions, inspect the actual failure and make a narrow reviewed change; do not add privileged mode to get past a startup error. Test that its image layers fit the 30 GB boot disk, its writable caches fit the ephemeral allowance and its total memory fits 8 GiB. Container startup/download readiness can take minutes. Verify a real generation before benchmarking; `/healthz` on the proxy only checks the proxy.

## Stop and verify

```sh
python -m inference_lab.lab stop
python -m inference_lab.lab status
```

Stop verifies local intent, Pulumi outputs and live ownership labels before destroying the session stack. If expiry already removed the cluster, it refreshes stale session state first. Keep the authenticated expiry task in place to cover cleanup races. A stopped marker makes repeated stop calls idempotent; `status` describes Pulumi outputs and is not a live cloud inventory.

Confirm the exact cluster is absent through GKE API/CLI, its managed instance group instances and boot disks are gone, and no workload-created load balancer, static IP, PVC disk or snapshot remains. This template creates no persistent model volume, Service of type LoadBalancer or static address. Inspect retained resources rather than inferring their absence from templates. Review billing after usage data settles.

Automatic expiry validates project, unique run name and the three ownership labels. It does not acknowledge a successful deletion request until absence is observed. A cluster initially missing at expiry is retried through a 30-minute creation grace window. A very late create, IAM failure, queue disablement or prolonged API outage can escape that window; there is no guaranteed billing cutoff. Prove expiry and interrupted-start recovery in the first supervised activation. Do not schedule unattended billable experiments until those checks pass.

The foundation retains the network, subnet, registry images, service accounts, queue and scale-to-zero expiry service. Registry storage, queue/Run usage and logs may cost money. To retire the whole lab: verify all sessions gone, remove no-longer-needed image artifacts, then preview/destroy the **foundation** explicitly as a separate owner action. Never use Fleet's teardown commands against this state.
