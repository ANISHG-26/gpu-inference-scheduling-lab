# Explain it as a small restaurant

Think of the model as a cookbook and vLLM as a kitchen. Loading the cookbook takes time and memory. A request is an order; its prompt is the preparation work, and generating each token is another cooking step. More simultaneous orders can increase throughput while making each customer wait longer.

Kubernetes rents rooms and decides where each kitchen fits. A pod's CPU and memory requests reserve scheduling capacity; limits constrain its consumption. A pod can stay Pending when no room has enough free capacity. The two-model overlay requires different hostnames, so two model pods cannot quietly share the same machine.

Ray is the front-of-house coordinator. Here Ray Serve runs small forwarding replicas, tracks their health and routes requests to them. They call a private Kubernetes Service; Kubernetes distributes new connections to ready model pods. Ray actor CPU quantities are logical scheduling resources, while Kubernetes imposes process resource limits. Neither substitutes for measuring actual utilization.

vLLM is the kitchen manager. It executes the model and manages attention KV cache, the working memory used to continue generating tokens. The model has a 1,024-token context cap, at most eight active sequences and a 512 MiB cache allowance. Eager execution avoids compilation overhead in this small CPU lab; this is not a performance-tuned configuration. The API permits at most 128 output tokens. Character limits at the API are a request-size bound, not a token-count guarantee; vLLM can reject a prompt that exceeds context. Eight maximum-length requests may need more cache than is available, so observe waiting/preemption rather than assuming all eight fit simultaneously.

Two complete model copies are two kitchens with the same cookbook. They can serve separate customers. One customer's order does not automatically finish sooner, and the weights occupy memory twice. Splitting one model across machines is a different experiment: the kitchens must communicate for one order. That is deferred until the replica experiment produces evidence.

## What the first experiment teaches

| Question | Observation to collect |
| --- | --- |
| Where did the work run? | Kubernetes pod-to-node placement, Ray actor placement and `X-Lab-Ray-Node` response header |
| What happens when requests arrive faster than service? | Successful latency, throughput, errors and bounded queue behavior |
| What happens when a model pod is lost? | Readiness removal, failed in-flight requests, download/reload delay and recovered capacity |
| Does a second node help? | Identical prompts, output bound and concurrency on one-node and two-node sessions |
| What does shutdown mean? | Exact GKE cluster and backing nodes/disks absent; retained foundation inventoried |

The API does not retry generation automatically. A client timeout does not prove the backend stopped generating immediately. Ray also has a bounded queue before the forwarding replica; a full system can return Ray's overload response rather than the core's 429. Record errors instead of hiding them with retries. The benchmark is non-streaming, so it does not measure time to first token.

## Later vocabulary

**Slurm** allocates computing resources to queued jobs: useful for batch work, priorities, wall-time limits and accounting. **Triton** serves models through supported backends and adds model repositories, versioning and batching. Learn each separately after the first serving lesson.

**NIM** is NVIDIA's packaged inference-service ecosystem; terms and hardware requirements vary by offering. **Nemotron** names model families, rather than a cluster scheduler. **Diffusion language models (dLLM)** refine masked/noisy text, while **Distributed Llama** distributes supported model computation across machines. Neither should be confused with vLLM, which is an inference engine. The [catalog](cpu-poc-plan.md) links their sources.

CPU runs teach placement, queues, failure, orchestration and communication costs. They provide no measured evidence about GPU kernels, VRAM isolation, CUDA, NVLink or GPU collective performance.
