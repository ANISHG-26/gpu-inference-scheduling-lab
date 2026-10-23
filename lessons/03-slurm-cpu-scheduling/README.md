# 03 — Slurm CPU queues and allocations

Prepared teaching material only. Evaluate SchedMD's Slinky/slurm-operator first; see the [version, privilege, cgroup, storage and capacity gates](../../docs/lesson-compatibility.md). No custom Slurm daemon packaging, disabled-cgroup workaround, privileged manifest or unauthenticated REST gateway is selected here.

Target experiment: two CPU execution slots, three fixed one-CPU jobs, short hard time limits, pending/running/completed observation, and cancellation of a job whose ID and lesson ownership were recorded by the adapter. `examples/short-job.sbatch` is an operator-reviewed future job input, not a browser-supplied script. A live adapter must use the chosen supported API/auth route and store job ownership; never expose arbitrary submit scripts or pod exec.

Predict the queue before submission. Observe Slurm allocations separately from Kubernetes worker placement. Inspect job limits and cancel only the recorded lesson job, then verify cancellation and allocation release. Run this lesson separately from inference. Omit accounting/login/HA unless required by the selected supported chart.

Acceptance remains blocked: exact compatible operator/CRD/chart/Slurm digest set; approved worker privilege/cgroup design on the actual GKE COS version; explicit resource budget; storage and teardown plan; bounded authenticated adapter; real queue/allocation/limit/cancel observations; scheduled expiry and no leaked volumes. The console displays the gate and provides no Slurm mutation controls.
