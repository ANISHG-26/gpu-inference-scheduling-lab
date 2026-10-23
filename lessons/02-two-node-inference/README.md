# 02 — Independent model replicas on two nodes

Entrypoint: `kubectl kustomize k8s/two-nodes`. The overlay defines two vLLM copies, two Ray workers, and two Serve replicas. Every model copy contains the full model. There is no model partitioning. Serve also sets `max_replicas_per_node: 1`: Kubernetes pod anti-affinity alone does not spread Ray replica actors. Use a fresh two-node session rather than changing a live RayService topology, which can create overlapping Ray clusters.

Prediction: will two copies make one request twice as fast, or mostly change concurrent capacity? First verify **actual** `pod.spec.nodeName`, model pod UID, StatefulSet ownership and Ready status. Required anti-affinity is desired placement, not proof it occurred. The console fails placement validation for missing/extra replicas, unready/terminating pods, overlapping Ray clusters, or model/worker replicas sharing a node.

Repeat lesson 01's model revision, dtype, prompt, context and token cap, with eight requests per concurrency 1/2/4/8 sample. Record node count, total reservations and actual pod placement with each comparison. Different total CPU/memory is an intentional variable; do not attribute improvements to Ray alone.

`X-Lab-Ray-Node` identifies the Ray node, **not the model pod that served a request**. The fixed Kubernetes Service balances upstream connections. The initial console records real model placement from the Kubernetes API and labels per-request model identity unknown. Do not claim both model pods served traffic solely from Ray headers or readiness. Per-backend request attribution remains a later acceptance gate; it requires model-side identity/metrics or a separately verified fixed per-pod adapter.

Recovery stays supervised outside the browser: record both model UIDs, replace one verified model pod, observe the survivor and replacement, and measure actual success/error/recovery. The read-only console cannot delete pods.

Validation on October 22, 2026 exercised actual model/worker placement, Serve actors on separate Ray nodes, real generation, comparable bounded load, replacement UID/readiness and a successful survivor canary through the console API. Scheduled expiry was registered and manual session cleanup was verified. Fresh two-node browser verification and per-request model attribution remain outstanding. One survivor canary does not establish continuous zero downtime. Review current CPU entitlement and quota before each new session.
