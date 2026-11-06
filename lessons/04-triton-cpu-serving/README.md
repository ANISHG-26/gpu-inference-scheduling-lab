# 04 — NVIDIA Triton Inference Server on CPU

This lesson serves a tiny deterministic model through NVIDIA Triton Inference Server. It teaches model repositories, numeric versions, tensor contracts, batching and metrics. The model doubles FP32 values; it is not a learned model or an LLM benchmark.

The pinned 26.09 runtime has passed real CPU readiness, correct tensor output, wrong-shape and missing-version errors, non-root execution, Python 3.12 linkage,128 MiB shared memory and the disk-reserve checks on the reviewed80 GB node. The [compatibility assessment](../../docs/lesson-compatibility.md) distinguishes that runtime evidence from the historical image evaluations. Console experiments and current deployment state are separate observations.

Predict the output and shape for `examples/valid-request.json`, then predict why `invalid-request.json` fails. Version 1 is the only configured version; a fixed probe verifies that version 2 is unavailable. The adapter always uses `lab_double` and its explicit version policy. It accepts no arbitrary model name, repository path, URL or script.

Each experiment contains eight input items with four FP32 values each. Client batch size 4 produces two HTTP requests. Inference count measures input items; execution count measures backend executions. A request batch can contain several items, and the server may combine requests. Concurrency alone does not prove server batching: compare actual counter deltas and keep client batch size fixed when testing that question.

Render the workload without creating resources:

```sh
kubectl kustomize lessons/04-triton-cpu-serving
```

The ConfigMap comes directly from this lesson's model repository. Two read-only subPath file mounts keep ConfigMap projection metadata outside Triton's model scan. Replace the pod after changing model files. The workload runs one non-root container with a read-only root, bounded temporary/shared-memory volumes and an HTTP-only ClusterIP Service. Only the operator may reach port 8000; metrics and gRPC have no Service.

Use the separately reviewed80 GB session disk plan for this pinned image; the original CPU lessons retain their30 GB default. Review the [session runbook](../../docs/runbook.md#start-a-disposable-session), retain immutable expiry, and run lessons sequentially. Deploying this model does not itself configure the operator's image, fixed API egress targets or session deadline.

Acceptance includes the real fixed-adapter experiment, valid/error/version behavior, counter deltas, current pod identity, browser controls and verified expiry cleanup. A Ready pod or a fixture test alone does not complete the lesson.
