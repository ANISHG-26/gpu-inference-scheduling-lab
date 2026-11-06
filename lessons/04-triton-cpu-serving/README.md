# 04 — NVIDIA Triton Inference Server on CPU

Prepared teaching inputs, isolated Kubernetes workload, fixed protocol adapter and console controls. This is NVIDIA's inference server, distinct from the Triton kernel language. The [compatibility note](../../docs/lesson-compatibility.md) records candidate image identities and unresolved runtime acceptance gates. No deployable image is selected and the catalog gate keeps the adapter disabled.

The tiny `model-repository/lab_double` model deterministically doubles FP32 inputs on CPU. It teaches repositories, numeric versions, tensor contracts, dynamic batching and metrics; it is not a learned model or an LLM benchmark. Version 1 is the only prepared version. The `version_policy` is explicit. The Python model imports the server-supplied Python backend utility only when run inside the eventual compatible Triton runtime. Source model behavior tests use a clearly labelled utility fixture and do not prove backend compatibility.

Predict the output and shape for `examples/valid-request.json`, then predict why `invalid-request.json` should fail. After compatibility acceptance, use fixed model/version adapters for readiness, valid/invalid requests, version selection and metrics. Contrast inference count and execution count under actual dynamic batching; request concurrency alone does not prove batching. Never expose arbitrary model names, repository paths, metrics URLs or request scripts.

The prepared controls always use eight input items, each containing four FP32 values. A client batch size of 4 produces two HTTP requests. Observed inference and execution counts are separate from request count; their ratio can describe server batching only after real measurements pass validation. Fixture tests do not establish batching.

Render the prepared workload without creating resources:

```sh
kubectl kustomize lessons/04-triton-cpu-serving
```

The render generates a ConfigMap directly from this lesson's model repository. It defines one non-root Triton pod, read-only file mounts for the model configuration and Python backend file, bounded temporary/shared-memory volumes, and an HTTP-only ClusterIP Service. Mounting only those two files keeps ConfigMap projection metadata outside Triton's `/models` repository scan. The mounts use `subPath`, so updating the ConfigMap does not update files in a running pod; replace the pod to pick up model changes. Only the operator may reach port 8000; metrics and gRPC have no Service. The image remains an intentionally unusable placeholder pending runtime acceptance. Do not apply this render as a working lesson or replace the placeholder with an unverified tag.

The session infrastructure accepts an explicit `lab:diskSizeGb` of 30 or 80, with 30 as the default. The larger option is for a separately reviewed Triton-only session, with the same immutable expiry and node bounds. Review actual disk headroom and runtime behavior before selecting an image. See the [session runbook](../../docs/runbook.md#start-a-disposable-session).

Acceptance: pinned CPU-compatible image/model inputs; measured extracted image+model+system disk headroom; non-root/writable-temp/shared-memory checks; real readiness and correct FP32 output; wrong-shape error; version behavior; observed batching/metrics; expiry cleanup. The October 23 candidate pull was aborted at the disk-reserve gate before Ready, and its disposable session was removed. No Triton backend execution or live adapter has been validated yet.

The revised file mounts have passed render checks only. Live pod startup and inference with this mount layout remain untested.
