# GPU stage prerequisite: prove GPU access

Status: not passed. After the October 22, 2026 CPU-first decision, this gate applies only to real GPU experiments. It does not block the CPU POC described in [the CPU plan](cpu-poc-plan.md).

The GPU stage requires a real GPU exposed as a Kubernetes allocatable resource. A working hosted AI API, CPU-only model, or GPU container outside Kubernetes does not establish that prerequisite.

## Infrastructure paths

| Path | Current planning conclusion | Required proof |
| --- | --- | --- |
| Unupgraded Google Cloud free trial | Cannot provision GPU VM instances or request quota increases | Select another path; do not attempt a deployment on this assumption |
| Google Cloud with paid billing enabled | Conditional candidate; remaining eligible welcome credit may still apply until its original expiry | Owner-approved billing change and cost plan, global and regional/model GPU quota, actual capacity, bounded infrastructure and teardown |
| Existing local GPU through Windows/WSL2 | Candidate, not a validated Kubernetes GPU environment | Compatible driver/runtime, container CUDA, device-plugin discovery, allocatable GPU, scheduled GPU pod |
| Accessible native Linux GPU host | Candidate if hardware access is available | Driver/runtime/device-plugin compatibility and the same Kubernetes allocation checks |

Paid billing must never be enabled automatically. A budget notification is not an assurance that resources cannot incur further costs. Quota also does not guarantee zone capacity.

Google's [trial policy](https://docs.cloud.google.com/free/docs/free-cloud-features) documents GPU and quota restrictions and what happens to remaining credit on upgrade. The [GPU quota documentation](https://docs.cloud.google.com/compute/resource-usage) distinguishes global and regional/model quotas and capacity availability.

## Local compatibility boundary

[Docker's Windows GPU support](https://docs.docker.com/desktop/features/gpu/) documents NVIDIA access through its WSL2 backend. That establishes a possible container route, not a working Kubernetes scheduler experiment. [Minikube's GPU guide](https://minikube.sigs.k8s.io/docs/tutorials/nvidia/) lists Linux prerequisites. Validate the exact host, runtime, device-plugin and telemetry combination rather than assuming either path works from successful host `nvidia-smi` output.

## Acceptance checks

1. Record the selected host/provider, GPU model, memory, driver, container runtime and Kubernetes versions. For rented resources, first record the approved experiment window, cost exposure, owner and teardown procedure.
2. Run one small CUDA operation inside a container and verify execution on the GPU. Successful device listing alone is insufficient.
3. Install the supported device plugin and verify a node advertises at least one allocatable `nvidia.com/gpu` with sharing disabled.
4. Schedule a pod requesting one GPU; successfully execute a small CUDA operation in that pod. Record actual device access and any visibility limits.
5. While the first pod holds its GPU allocation, observe a second one-GPU pod remain Pending for insufficient GPU resources; then release the first and observe the second run.
6. Verify cleanup and retain the exact commands, observed events and limitations.

If these checks fail, stop implementation expansion and diagnose the access path. CPU simulation may test orchestration code but must remain explicitly labeled simulation; it does not pass this milestone.

## Scope after passing

Use one GPU, one model, fixed prompts, and one runtime. Add model readiness, cold/warm timing, request metrics and restart recovery to the verified allocation experiment. Study priority next. Sharing, multiple GPUs, distributed execution, custom schedulers and broad platform features are later decisions requiring a measured question.
