# First experiment: exclusive GPU contention

Status: proposed; no hardware run completed.

## Question

When one worker exposes one allocatable GPU, how does Kubernetes handle two pods that each request one exclusive GPU, and what changes after the running pod releases it?

## Prerequisites

- Select an accessible real GPU and supported Linux/container runtime/driver/device-plugin combination.
- Verify allocatable GPU capacity and model memory fit. GPU access through the chosen virtualization path must be demonstrated.
- Record permission to use the environment, resource limits, session duration, cost exposure, and cleanup steps before provisioning.
- Choose and pin Kubernetes, device plugin, inference runtime, image, model revision, and quantization.
- Define a fixed prompt set, context size, output limit, concurrency, and request arrival pattern.

## Proposed procedure

1. Observe the node's advertised `nvidia.com/gpu` capacity and allocatable count.
2. Submit one model-serving pod requesting one GPU; capture placement and startup events.
3. Confirm actual GPU inference and readiness, then run a bounded request workload.
4. Submit a second pod requesting one GPU. Capture its Pending state and scheduling reason.
5. Delete the first experiment pod and observe the second becoming schedulable. Account for device release and model-loading delay.
6. Clean up all experiment resources and verify the final inventory.

This baseline uses exclusive allocation with sharing disabled. A time-slicing configuration advertises different capacity and requires a separate experiment.

## Required evidence

- Node capacity, workload manifests, events, observed state transitions, and timestamps.
- GPU process/memory/utilization evidence and the inference runtime's device information.
- Cold loading versus warm inference latency, time to first token, throughput, request errors, and workload parameters.
- Reproduction and teardown commands, observed limitations, and conclusions tied to results.

Do not infer real GPU performance from a fake device plugin or multiple virtual nodes on one GPU.

## Follow-up comparisons

- Placement: selectors/affinity, taints/tolerations, namespace quotas.
- Priority: pending workloads and pod preemption; distinguish pod eviction from GPU kernel preemption and from inference queue priority.
- Sharing: supported time slicing versus exclusive allocation, including memory interference, failures, fairness and p95 latency.
- Replicas: independent model-serving workers and request distribution when more hardware is available.

Use [NVIDIA's device plugin](https://github.com/NVIDIA/k8s-device-plugin), [Kubernetes GPU scheduling](https://kubernetes.io/docs/tasks/manage-gpus/scheduling-gpus/), and [NVIDIA sharing documentation](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/gpu-sharing.html) when choosing implementation versions.
