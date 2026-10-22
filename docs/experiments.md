# Small experiments, honest observations

Use a new session for each topology. Do not update a running RayService's cluster specification: KubeRay may create a replacement cluster alongside the active one. Destroy/recreate keeps the initial experiment within its intended capacity. Never increase nodes because a pod is Pending without diagnosing its resource requests.

1. **Predict:** one request should finish; eight concurrent requests may improve total throughput but increase individual waiting time. Record the prediction before measuring.
2. **Baseline:** wait for model readiness and one real generation; separate cold model download/loading from warm runs. Save node CPU flags, image digests, model revision, pod placement, requests/limits and engine logs without request text.
3. **Load:** run concurrency 1, 2, 4 and 8 separately with the same 32-token maximum. Keep the request count, prompt, model context and precision fixed. Save successful p50/p95, errors and aggregate completion tokens per second. Report sample count; small-sample percentiles are coarse.
4. **Failure:** while sending bounded requests, delete exactly one `vllm` pod in the disposable namespace. Observe readiness and replacement, errors during recovery, and cache reload. Do not claim exactly-once generation or zero failed requests.
5. **Two nodes:** stop and verify the baseline session. Set `node_count: 2`, start a fresh session and use `k8s/two-nodes`. Confirm two model pods on different nodes and record Ray placement. Run the same load. Two nodes also double model/worker capacity; this is a capacity comparison, not proof that networking accelerated one generation.
6. **Explain back:** which layer chose each placement? Where did requests wait? What memory was duplicated? What failed, and which controller restored it?
7. **Shutdown:** stop, verify exact resources absent and inventory the foundation. Report measured evidence separately from expectations.

Example through the private forwarded API:

```sh
python -m inference_lab.benchmark --requests 20 --concurrency 2 --max-tokens 32 --output results/local/warm-c2.json
kubectl -n inference-lab get pods -o wide
kubectl -n inference-lab top pods
kubectl -n inference-lab get events --sort-by=.metadata.creationTimestamp
```

Create `results/local` first. Reports never overwrite an existing file, and omit generated text. The benchmark sends a fixed public greeting prompt. It uses no retries and measures complete non-streaming response time; time to first token needs a later streaming experiment.

For engine metrics, port-forward `service/vllm` to a separate local port and inspect `/metrics`. Ray exposes its own Serve metrics and dashboard internally. Operator-controlled port-forwards must remain bound to localhost. Preserve metrics snapshots as private evidence before shutdown; a permanent monitoring stack is outside this first delivery.

Report template: date / code revision / images / model revision / hardware / CPU flags / topology / workload / cold-or-warm / placement / latency / throughput / errors / memory / prediction versus result / limitation / exact shutdown evidence. Do not publish account IDs, raw tokens, credentials or private recordings.
