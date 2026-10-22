# 02 — Independent model replicas on two nodes

Entrypoint: `kubectl kustomize k8s/two-nodes`. This preserves the existing two-node overlay: two vLLM copies, two Ray workers, and two Serve replicas. Every model copy contains the full model. There is no model partitioning. Use a fresh two-node session rather than changing a live RayService topology, which can create overlapping Ray clusters.

Prediction: will two copies make one request twice as fast, or mostly change concurrent capacity? First verify **actual** `pod.spec.nodeName`, model pod UID, StatefulSet ownership and Ready status. Required anti-affinity is desired placement, not proof it occurred. The console fails placement validation for missing/extra replicas, unready/terminating pods, overlapping Ray clusters, or model/worker replicas sharing a node.

Repeat lesson 01's model revision, dtype, prompt, context and token cap, with eight requests per concurrency 1/2/4/8 sample. Record node count, total reservations and actual pod placement with each comparison. Different total CPU/memory is an intentional variable; do not attribute improvements to Ray alone.

`X-Lab-Ray-Node` identifies the Ray node, **not the model pod that served a request**. The fixed Kubernetes Service balances upstream connections. The initial console records real model placement from the Kubernetes API and labels per-request model identity unknown. Do not claim both model pods served traffic solely from Ray headers or readiness. Per-backend request attribution remains a later acceptance gate; it requires model-side identity/metrics or a separately verified fixed per-pod adapter.

Recovery stays supervised outside the browser: record both model UIDs, replace one verified model pod, observe the survivor and replacement, and measure actual success/error/recovery. The read-only console cannot delete pods.

Acceptance: two Ready models on distinct nodes and two Ready workers on distinct nodes in one Ray cluster; real generation; comparable load rows; surviving replica behavior and recovered UID/Ready plus generation; no stale result reused after pod changes; expiry and complete session cleanup. No two-node measurement has been recorded yet. Eight vCPUs require a current cross-project entitlement/quota check before activation.
