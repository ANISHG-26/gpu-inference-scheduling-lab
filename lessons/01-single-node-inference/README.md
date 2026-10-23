# 01 — Single-node inference

The [October 22 baseline](../../docs/results/2026-10-22-cpu-baseline.md) ran real Qwen3-0.6B inference through Ray Serve. That session expired and was removed. This folder prepares its teaching flow; it does not represent a running environment.

Entrypoint: `kubectl kustomize k8s/base`. Preserve the model revision, float32 precision, 1,024-token context, 512 MiB KV cache, eight sequences, two CPU threads, and 8 GiB model reservation. The [shared runbook](../../docs/runbook.md) owns provisioning and expiry. Add the [operator](../../operator/README.md) only after its extra reservation fits the reviewed node capacity.

1. Predict which component controls pod placement, request routing, and token scheduling.
2. Inspect one Ready model UID, one Ray head, and one worker on one node in the console.
3. Warm once, then run separate eight-request samples at concurrency 1, 2, 4, and 8. Keep the fixed greeting prompt and 32-token cap. Record results privately before a restart loses the console's in-memory result.
4. Compare p50/p95 latency, errors, and aggregate output tokens/sec. Eight samples do not establish production tail latency.
5. For recovery, an out-of-browser operator deletes only the verified model pod during an explicitly supervised exercise. Observe old/new UIDs, readiness and first real successful generation. There is no console delete/exec permission.

Acceptance checklist: exact run/deadline recorded; node fit verified; real generation with token usage; 32/32 bounded requests or actual errors recorded; replacement UID and generation recovery timed; scheduled expiry and backing-resource absence verified. Console fixtures and the historical report are separate evidence.
