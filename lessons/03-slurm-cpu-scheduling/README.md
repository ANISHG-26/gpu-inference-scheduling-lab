# 03 — Slurm CPU queues and allocations

Prepared teaching material only. Evaluate SchedMD's Slinky/slurm-operator first; see the [version, privilege, cgroup, storage and capacity gates](../../docs/lesson-compatibility.md). No custom Slurm daemon packaging, disabled-cgroup workaround, privileged manifest or unauthenticated REST gateway is selected here.

Target experiment: two CPU execution slots, three fixed one-CPU jobs, short hard time limits, pending/running/completed observation, and cancellation of a job whose ID and lesson ownership were recorded by the adapter. `examples/short-job.sbatch` is an operator-reviewed future job input, not a browser-supplied script. A live adapter must use the chosen supported API/auth route and store job ownership; never expose arbitrary submit scripts or pod exec.

Predict the queue before submission. Observe Slurm allocations separately from Kubernetes worker placement. Inspect job limits and cancel only the recorded lesson job, then verify cancellation and allocation release. Run this lesson separately from inference. Omit accounting/login/HA unless required by the selected supported chart.

Acceptance remains blocked: exact compatible operator/CRD/chart/Slurm digest set; approved worker privilege/cgroup design on the actual GKE COS version; explicit resource budget; storage and teardown plan; bounded authenticated adapter; real queue/allocation/limit/cancel observations; scheduled expiry and no leaked volumes. The console displays the gate and provides no Slurm mutation controls.

`evidence.py` validates a normalized, offline evidence object only. It expects
lesson ID `03`, run and owner identifiers, `source` (`fixture` or `live`),
nonempty provenance, a positive finite `expires_at`, three uniquely identified
one-CPU registrations (each limited to 60 seconds), one recorded cancellation,
and three timestamped snapshots named `queued`, `released`, and `finished`.
Each snapshot lists all three jobs with `job_id`, Slurm `state`, and
`allocated_cpus`; live provenance also carries `cluster_uid`, `worker_uid`,
and `collector`. The validator returns `structurally_valid` and `source` only.
Fixtures exercise the parser and are not acceptance evidence. Even a `live`
source label does not establish authenticity, causality, cgroup enforcement,
effective runtime limits, expiry cleanup, or cloud acceptance. Live API mapping,
authentication, and job ownership remain unselected; the acceptance gate above
is unchanged.
