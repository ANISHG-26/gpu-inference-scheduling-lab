# CPU proof of concept: inference under load

Direction accepted October 22, 2026. Updated decision: Kubernetes is the first deployment target, with Pulumi Python provisioning. The [current architecture](architecture.md), [runbook](runbook.md) and [preparation evidence](preparation.md) supersede the earlier VM-first sequencing below. Real model and cloud acceptance remain open.

## Purpose

Use eligible Google Cloud trial CPU resources to learn model-serving and distributed-computing infrastructure on Kubernetes. Progress from one real model server to two independent replicas. Model partitioning and GPU hardware are later experiments.

Keep the first delivery small: one model family, fixed prompts, one CPU GKE node initially, at most a second node for replica work, bounded runtime and explicit cleanup. The project is independent of F0ToFret and Ottawa Fleet Platform.

## Official source and distribution candidates

| Component | Source license | Published source/distribution |
| --- | --- | --- |
| Ray / Ray Serve | Apache-2.0 | [Repository](https://github.com/ray-project/ray); official `rayproject/ray` images include CPU variants; [installation docs](https://docs.ray.io/en/latest/ray-overview/installation.html) |
| vLLM | Apache-2.0 | [Repository](https://github.com/vllm-project/vllm); official `vllm/vllm-openai-cpu` images; [CPU docs](https://docs.vllm.ai/en/latest/getting_started/installation/cpu/) |
| Qwen3 0.6B | Apache-2.0 model license | [Publisher's model card and weights](https://huggingface.co/Qwen/Qwen3-0.6B) |
| Distributed Llama | MIT | [Repository](https://github.com/b4rtaz/distributed-llama); build a pinned project image from source if selected |
| llama.cpp | MIT | [Repository](https://github.com/ggml-org/llama.cpp); alternative CPU baseline if runtime fit warrants it |
| Triton Inference Server | BSD-3-Clause core | [Repository](https://github.com/triton-inference-server/server); `nvcr.io/nvidia/tritonserver` images; [CPU quickstart](https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/getting_started/quickstart.html) |
| Slurm | GPL-2.0 with project notices/exceptions | [Repository](https://github.com/SchedMD/slurm); separate later CPU batch-scheduling lesson |

Image names identify publishers, not selected release tags. Pin verified releases and image digests during implementation. Container contents and dependencies may have additional licenses. Model weights and tokenizer revisions are pinned separately from runtime software. Avoid treating all NVIDIA software or models as carrying one open-source license: NIM availability and terms vary by offering.

## Milestone zero: CPU compatibility and cost

- Inspect available project CPU/RAM/storage quotas and proposed host CPU capabilities without changing billing.
- Check the selected vLLM release and image against Linux, CPU instruction set, model architecture, dtype and memory limits. Upstream recommends AVX512 and documents limited-feature AVX2 support; an arbitrary inexpensive VM is not automatically compatible.
- Bound model context, output length, concurrency and cache memory before sizing the VM. Model download size is not total RAM demand.
- Validate Ray plus serving-engine integration explicitly. Ray orchestrates application workers/replicas; its presence alone does not establish support for vLLM's internal distributed executor on CPU.
- Record intended VM count, machine sizes, region, disk, networking, session cost, shutdown/deletion procedure and remaining trial entitlement before provision. Trial credits do not make every Google service eligible.
- Run one real generation request in the selected CPU environment. If vLLM cannot fit the chosen environment, compare the cost/scope of another compatible CPU target with a llama.cpp baseline rather than silently changing claims.

## Experiment A: a single model server

Serve a small model such as Qwen3 0.6B through the CPU engine. Establish request schema, streaming where supported, readiness, cold loading and warm execution. Vary prompt length, maximum output and concurrent requests one at a time.

Record wall time, time to first token, generated token count, tokens/second, p50/p95 latency, errors, process memory and CPU usage. Keep warm/cold samples and workload settings visible. Fixed prompts and bounded generation make runs comparable; response quality remains a separate concern.

## Experiment B: independent replicas and recovery

Use Ray tasks/actors and Serve to place application work across two CPU machines, with one complete model copy per serving replica. Validate exact integration and per-node memory before enabling a second replica. Keep Ray management interfaces inside the experiment's private network and use operator-controlled access.

Demonstrate placement, routing, queueing under controlled load, a worker loss and recovery. Record which requests fail or are retried, and how model reload affects readiness. Define retry/idempotency behavior rather than assuming execution is exactly once.

This distributes separate requests. A single request is not automatically faster, and total memory for weights generally increases with another complete replica. Ray CPU resource declarations are logical scheduling admission controls, not CPU usage enforcement.

## Experiment C: one model across two machines

Evaluate Distributed Llama with a supported small checkpoint. Its repository lists Qwen3 0.6B and constrains node counts to powers of two, with additional model and quantization restrictions. Verify the exact pinned revision before using it.

Compare that engine on one node with the same engine/model/precision on two nodes. Record aggregate CPU/memory allocations, network traffic, synchronization, generation latency, throughput and failure behavior. Do not attribute a cross-engine or unequal-resource comparison solely to distribution.

The goal is to understand communication cost and model partitioning. A slower two-node run is a valid result. CPU networking does not reproduce GPU collectives, NVLink/RDMA behavior, GPU memory management or hardware kernel performance.

## Later lessons

- Triton CPU: model repository, versions, supported backends, dynamic batching, readiness and metrics using a small supported ONNX/classification/embedding model. This is model-serving evidence, not proof of GPU LLM execution.
- Slurm CPU: allocations, job queues, priorities, execution limits and accounting. Run as a separate lesson rather than layering another scheduler into the first serving experiment.
- Kubernetes is now part of the first delivery: examine pod placement and lifecycle separately from Ray task placement and model execution.
- Real GPU: use [the GPU feasibility checks](feasibility-gate.md), then the [GPU contention experiment](experiment-plan.md).

## Naming: dLLM versus distributed inference

Diffusion language models refine masked/noisy text over successive steps. The [dLLM research framework](https://github.com/ZHZisZZ/dllm) studies that model family. This differs from distributing an autoregressive model across machines. Diffusion is an optional future model-architecture lesson, with checkpoint/runtime/hardware suitability to be verified separately.

Neither the term dLLM nor the name vLLM by itself specifies a distributed topology. The POC report must always say whether it uses independent model replicas or a partitioned model.
