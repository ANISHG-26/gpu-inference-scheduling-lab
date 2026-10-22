"""Small teaching catalog; deployment and measurements come from observations."""

CATALOG = (
    {
        "id": "01-single-node-inference",
        "title": "One node: the inference baseline",
        "objective": "Separate Kubernetes placement, Ray routing, and vLLM token scheduling.",
        "prediction": "What will change in latency and total output throughput as concurrency rises?",
        "steps": [
            "Observe one Ready model pod, one Ray head, and one worker on the same node.",
            "Write a prediction, then send eight fixed requests at concurrency 1, 2, 4, or 8.",
            "Compare latency, errors, and output tokens per second; keep the model and prompt fixed.",
            "During a supervised recovery exercise, observe the model UID and readiness change.",
        ],
        "reflection": "Which layer schedules pods, which routes requests, and which schedules tokens?",
        "gate": None,
    },
    {
        "id": "02-two-node-inference",
        "title": "Two nodes: independent model copies",
        "objective": "Verify full replicas on distinct nodes, then compare bounded load and recovery.",
        "prediction": "Will two complete model copies halve a single request's latency? Why?",
        "steps": [
            "Verify two Ready vLLM pod UIDs on two different node names and two separated Ray workers.",
            "Repeat the baseline's eight-request samples with the same model, precision, and token cap.",
            "Compare aggregate throughput and latency; Kubernetes placement is separate from routing.",
            "Observe a supervised pod replacement and record the new UID, readiness, and errors.",
        ],
        "reflection": "What proves model placement? What additional evidence would prove which pod served a request?",
        "gate": None,
    },
    {
        "id": "03-slurm-cpu-scheduling",
        "title": "Slurm: queues and allocations",
        "objective": "Explain pending jobs, CPU allocations, limits, and owned-job cancellation.",
        "prediction": "With two execution slots and three one-CPU jobs, which job should wait?",
        "steps": [
            "Resolve the upstream Slinky privilege, cgroup, version, storage, and capacity gates first.",
            "In a separate session, submit only the fixed short CPU job and inspect pending/running states.",
            "Compare Slurm allocations with the outer Kubernetes worker-pod placement.",
            "Cancel only a recorded lesson-owned job; verify its final state and bounded time limit.",
        ],
        "reflection": "Why is a Kubernetes pod's CPU limit different from a Slurm allocation?",
        "gate": "Slinky worker privilege/cgroup, Kubernetes compatibility, storage, and resource gates remain unresolved. No live adapter is enabled.",
    },
    {
        "id": "04-triton-cpu-serving",
        "title": "Triton: model repositories and batching",
        "objective": "Serve a tiny deterministic CPU model and inspect versions, batches, and metrics.",
        "prediction": "How should a batched request change execution count versus inference count?",
        "steps": [
            "Resolve the exact Triton image digest, disk footprint, Python ABI, shared memory, and non-root gates first.",
            "Inspect a model repository's config and numeric version directories; select a version explicitly.",
            "Send the prepared valid and invalid tensor requests, then inspect readiness and sanitized errors.",
            "Compare batching configurations using actual metrics; do not infer GPU or LLM performance.",
        ],
        "reflection": "How do the model name, version, tensor shape, and backend affect a request?",
        "gate": "Triton CPU image digest/disk footprint and non-root/Python ABI/shared-memory validation remain unresolved. No live adapter is enabled.",
    },
)
