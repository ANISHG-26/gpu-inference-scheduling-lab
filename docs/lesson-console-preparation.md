# Lesson console: preparation and acceptance

This slice preserves the validated inference CLI, Pulumi foundation/session separation, expiry controller and one/two-node Kustomize entrypoints. Shared teaching text is in `inference_lab.lessons`; lesson-specific materials and evidence checklists are under `lessons/`. The operator serves buildless assets and a same-origin API from inside the cluster. Its ServiceAccount can only list pods in `inference-lab`. It cannot read secrets/logs, exec, delete, deploy or provision resources.

The first adapter sends eight fixed greeting requests to the private Ray Serve Service, with 32 output tokens and concurrency 1/2/4/8. One experiment is admitted at a time. The latest result is volatile memory, with no durable history; save accepted measurements privately before restarting. Pod UID/owner/readiness/actual node checks validate the whole active inference topology before and after a run. Balanced per-request model identity is unknown; Ray headers do not solve it. Recovery is supervised outside the browser, observed through the console's pod table.

`prepared` means catalog/materials exist. `deployed` requires current Ready topology. `measured` requires completed inference evidence and unchanged Ready topology during a run. `failed` records experiment or required-pod failure. Observation failures and expired sessions disable actions. No fixture or old baseline is displayed as live cluster evidence. An expiry countdown does not prove cloud deletion.

## Activation inputs

`k8s/operator` is deliberately not part of either original inference entrypoint. Render it separately after reviewing fit. The template defaults to no active lesson, actions disabled and expiry zero. Its image is a placeholder. Network egress to the API uses a documentation-only TEST-NET /32 and fails closed until replaced. Do not apply the raw template and infer live integration from successful deployment.

Create an ignored `.lab` overlay that supplies these inputs:

1. A registry digest for the reviewed `containers/operator.Dockerfile` image. Pin the Python base identity before activation too.
2. `ACTIVE_LESSON=01-single-node-inference` or `02-two-node-inference`; no other live adapters exist.
3. `LAB_EXPIRES_AT` copied verbatim from the immutable **current** session ownership record, never the old run or a UI-generated deadline. Enable `LAB_ACTIONS_ENABLED=true` only for the supervised experiment session.
4. Replace `/spec/egress/2/to/0/ipBlock/cidr` in NetworkPolicy `lab-operator` with the exact current Kubernetes API endpoint /32. Verify GKE datapath Service translation, DNS, and the namespace pod-list request. Keep egress port 443 and the fixed Ray port 8000; do not fall back to general Internet access.
5. Set `EXPECTED_RAY_CLUSTER` to the current `inference-serve-svc` Service selector's `ray.io/cluster` value, verified outside the browser after Ray becomes Ready. The pod observer requires that exact owner and label, plus the Serve/node labels. Without the binding, placement validation fails closed. Recheck it after any RayService replacement; a matching unrelated RayCluster is insufficient.

Verify the target kube context/run labels and the session still has enough time, then deploy the inference lesson and console. Access only with `kubectl -n inference-lab port-forward --address=127.0.0.1 service/lab-operator 18080:8080`. The local browser's Host and Origin must match. Health probes use `/healthz`; this reports the console process, not model readiness.

## Resource plan for owner review

Reuse the retained dedicated lab project/foundation. No changes to Fleet/F0, billing, GPU quota or foundation resources are proposed. The next activation should begin with **one** `n2-standard-4` CPU node, 30 GB standard boot disk, no autoscaling/surge/GPU, and a **90-minute immutable lifetime starting before provisioning**. Inference keeps its measured reservations: model 2 CPU/8 GiB, Ray head 250m/1 GiB (limit 2 GiB), worker 750m/2 GiB. The console adds **25m CPU /64 MiB requested**, capped at **100m/128 MiB**. The existing namespaced KubeRay operator remains required.

The measured baseline reserved about 97% of allocatable memory, so the extra 64 MiB must be checked against actual system and operator reservations before workload activation. Do not reduce the model's 8 GiB reservation. If it does not fit, stop and revise the concrete plan. A later **separate** two-node session uses eight vCPUs/32 GiB host RAM and two 30 GB disks, two model copies/workers and one Ray head/console. Check current cross-project trial entitlement/quotas before it. Never overlap sessions or mutate a live RayService topology.

Expiry registration must precede provisioning through the existing lifecycle. Verify exact previous-session absence first. The UI has no start/extend/stop cloud controls. Scheduled expiry retains the foundation, registry images, source bucket, identities, queue and expiry service; storage/builds/logs/requests may cost. A price estimate is not a hard cap. Slurm and Triton are excluded from this activation pending their separate gates.

## Verification boundary

Source and fixture checks, image builds, browser integration and real cluster acceptance are separate. Record exact commands/results in the current continuation checkpoint. Required cloud acceptance: actual console resources fit; pod-list RBAC/network policy work without broader privileges; page loaded through the one port-forward; current UID/node/readiness and immutable countdown shown; one bounded real inference sample succeeds; failures/expiry disable controls; scheduled cleanup and VM/disk absence verified. Two-node placement/load/recovery, per-model traffic attribution, Slurm and Triton remain unmeasured until their own experiments run.

Preparation checks on October 22, 2026: 52 tests passed, including HTTP framing, response-size/redirect/slow-response boundaries, topology, expiry, failure persistence, and deterministic model arithmetic using a utility fixture. The isolated Pulumi mock, three Kustomize entrypoints, both Ray schemas, four Ray adapter checks, JavaScript syntax and dependency consistency passed. The operator image built locally and its non-root/read-only/capability-free import check passed. Independent source review found no remaining blocking findings after corrections. These results do not establish cloud acceptance. The HTTP deadline bounds connected requests; Python cannot interrupt a stalled DNS resolver, so it is not a guaranteed wall-clock bound for DNS failure.
