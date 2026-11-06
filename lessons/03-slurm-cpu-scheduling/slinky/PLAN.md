# Slinky CPU profile — offline plan

`plan-values.yaml` is a proposed values overlay for local, offline inspection
against the cached, mutually matched Slinky 1.2.1 chart and CRD archives. It is
not an install flow and does not select or authorize deployment. Do not copy
the archives into the repository. The 1.2.1 tuple is a concrete cached
candidate, not a claim that it is the latest release. Its image tags are still
unselected and must be replaced with verified immutable image identities
before activation.

## Planned shape

- One controller, one `lesson` worker, one `slurmrestd` replica; accounting
  disabled; no login sets; REST service remains `ClusterIP`.
- Controller persistence is disabled for this disposable exercise. Controller
  save-state is lost when its pod or release is removed or recreated.
- `nodesetDefaults.extraConfMap.CPUs: "2"` advertises two Slurm CPU slots on
  the four-vCPU worker. This is Slurm scheduling capacity only; it does not
  enforce a two-CPU cgroup boundary in Kubernetes.
- The single NodeSet-created default `lesson` partition has
  `MaxTime: "00:01:00"`. This caps job time, not queue length, job count, or
  per-user submission rate. Those need separate bounded-adapter controls.

## Proposed resource budget

The requests and limits in the values file are planning caps, not upstream
minimums, measured usage, or proof of node fit. Main containers and long-running
sidecars are budgeted separately:

| Pod component | Container | Request (CPU / memory) | Limit (CPU / memory) |
|---|---|---:|---:|
| Controller | `slurmctld` | 250m / 256Mi | 500m / 512Mi |
| Controller | reconfigure sidecar | 50m / 64Mi | 100m / 128Mi |
| Controller | logfile sidecar | 25m / 32Mi | 50m / 64Mi |
| Worker | `slurmd` | 2 / 1Gi | 2 / 2Gi |
| Worker | operator-managed logfile helper | 25m / 32Mi | 50m / 64Mi |
| REST | `slurmrestd` | 100m / 128Mi | 250m / 256Mi |

This profile adds no custom init containers. The operator generates managed
helper containers; inspect their exact init/sidecar behavior and account for
startup peaks before calculating the final pod scheduling footprint.
This budget excludes the operator, webhook, cert-manager, any scoped user
interface, Kubernetes/system overhead, and image disk/cache headroom; calculate
those before selecting node shape or claiming fit.

## Offline render boundary

Use only the cached chart archives as input. A future local Helm render may
select only the Controller, NodeSet, and REST API custom-resource templates
for inspection. It must not install, contact a cluster, or expose generated
Secret resources or their data in logs, artifacts, diffs, or reports. No
runtime validation is implied. A local render against the cached 1.2.1 Slurm
chart produced exactly the three intended CRs, with the planned resources,
ephemeral controller, private REST service and one-minute partition. No Secret
or PVC objects were included in the selected render. This checks chart field
mapping, not the operator-generated pods, CPU isolation or live behavior.

## Activation blockers

- The tagged 1.2.1 worker builder runs `slurmd` privileged and adds
  `BPF`, `NET_ADMIN`, `SYS_ADMIN`, and `SYS_NICE`. This conflicts with the
  current baseline until the owner explicitly accepts a supported privilege
  design and a matching disposable-node check succeeds.
- Cgroup-v2 delegation and enforcement on the exact GKE COS node remain
  unverified. Advertising two Slurm CPUs is not evidence of cgroup isolation.
- Immutable image digests, actual node/resource fit, image disk headroom,
  controller state-loss behavior, and teardown/reclaim behavior need decisions
  and evidence.
- The chart's native JWT settings do not provide the lesson's authenticated,
  bounded job-ownership adapter. Keep REST private; do not expose direct
  mutation access or invent an auth adapter.
- Real queueing, one-minute enforcement, owned cancellation, allocation
  release, expiry, and leak-free teardown remain live acceptance work.

Until these gates are resolved, lesson 03 remains preparation-only and
deployment stays off.
