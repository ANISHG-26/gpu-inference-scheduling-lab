# First CPU baseline — October 22, 2026

Real inference ran on one GKE `n2-standard-4` node: four vCPUs, 16 GiB host RAM, AVX512 available, 30 GB boot disk. Kubernetes scheduled one vLLM pod and a Ray head/worker pair on that node. The RayService reached Ready with a healthy application. A generated response included a Ray node header and nonzero model token usage, proving the forwarding path exercised the actual model.

Model: Qwen3-0.6B, publisher revision `c1899de289a04d12100db370d81485cdf75e47ca`. Runtime: vLLM CPU 0.27.1 at the digest in the manifest, float32, context 1,024, maximum eight sequences, 512 MiB KV cache, eager execution and two OpenMP threads without CPU binding. Ray 2.59.0 runs the forwarding application; its built image digest was `sha256:796b505405eb22c0d02cfa5cdb3ef2dd6dec899854e28fa0aad215645a34f64e`. The runtime configuration was committed at `0ec0b42`.

## Warm load samples

Each row sent eight independent requests through a localhost port-forward to the private Ray Serve Service. The same public greeting prompt and 32-token output maximum were used. One real generation warmed the model first. Runs were sequential, without client retries; generated text was not retained in the metrics.

| Client concurrency | Completed / errors | p50 seconds | p95 seconds | Aggregate output tokens/second | Run seconds |
| --- | --- | --- | --- | --- | --- |
| 1 | 8 / 0 | 9.274 | 10.108 | 3.378 | 75.792 |
| 2 | 8 / 0 | 9.858 | 12.741 | 5.948 | 43.036 |
| 4 | 8 / 0 | 9.924 | 10.376 | 12.786 | 20.022 |
| 8 | 8 / 0 | 12.315 | 12.322 | 20.773 | 12.323 |

More simultaneous requests improved aggregate throughput in this sample while increasing median request latency. This is consistent with batching and shared capacity on one model server; the measurements do not isolate batching from other effects. It does not demonstrate multi-node scaling, model partitioning or GPU performance. With eight observations, nearest-rank p95 is simply the slowest request; it is not a reliable production tail estimate. These non-streaming measurements do not include time to first token or evaluate answer quality.

## Capacity and startup findings

The node reported 3,920 millicores and about 12.96 GiB allocatable after system reservation. All pods together reserved about 97% of that capacity. The model retains an 8 GiB request and limit. The final configuration's successful startup reached about 7.23 GiB cgroup peak memory; lowering its reservation to 7 GiB was rejected. Cgroup memory includes more than process RSS, and this is startup evidence rather than an exhaustive worst-case bound.

The original Ray head's 1 GiB limit caused Ray's memory monitor to repeatedly kill the Serve controller, even though the Kubernetes container restart count remained zero. Raising only its limit to 2 GiB allowed startup; its reservation stayed 1 GiB. The replacement head initially measured about 1.05 GiB current and 1.16 GiB peak usage. This allows bursts and warrants monitoring node pressure; it is not a fully reserved peak-memory design. Old Ray resources were deleted and verified absent before recreation, avoiding overlapping Ray clusters.

Other activation fixes covered writable non-root image builds, the Cloud Tasks REST request envelope, Pulumi's additional-zone semantics, Ray shared token authentication, the supported vLLM logging flag and Kubernetes Service environment-variable collisions. The actual-image CLI check now parses the manifest's complete arguments with network access disabled. [CI for the measured code](https://github.com/ANISHG-26/gpu-inference-scheduling-lab/actions/runs/39803436145) passed all five checks.

## Pod replacement

Deleting the single model pod produced seven probes that reached their 15-second client timeout. The first successful generation finished about 182.3 seconds after deletion began. The StatefulSet replaced the pod with a different UID, the replacement became Ready, and the response again carried Ray routing evidence and nonzero model token usage. Probes were separated by ten seconds, so this measures observed recovery rather than the exact instant readiness returned. Ray remained deployed throughout. No zero-downtime or in-flight-request preservation claim is made for a single model replica.

## Remaining acceptance

Scheduled expiry was subsequently verified: the dedicated expiry identity initiated deletion at 16:28:01 UTC after the immutable 16:27:58 deadline. The GKE operation completed at 16:33:08. At 16:35:05 the API returned 404 and the owned instances, boot disks and managed groups were all absent; forwarding rules, reserved addresses and snapshots were also zero. No manual cloud-deletion fallback was used. Pulumi session state was reconciled only after absence verification. [Issue #1](https://github.com/ANISHG-26/gpu-inference-scheduling-lab/issues/1) records acceptance and closure.

The network/subnet, scoped identities, registry images, private source bucket with one-day deletion lifecycle, task queue and scale-to-zero expiry service remain. Retained storage/requests/logs may still cost; no final billing total is claimed. A later two-node session, cluster console, Triton and Slurm remain separate experiments.
