# Preparation evidence

Prepared on Windows / Python 3.12, October 22, 2026. Related delivery: repository issue #1. Work remains on `codex/cpu-kubernetes-lab`; the owner requested one PR and deployment at the next check-in.

| Evidence | Result |
| --- | --- |
| Standard library behavior suite | 33 tests passed, including actual local HTTP success/error/timeout fixtures |
| Pulumi resource mock | Passed in an isolated process; checks CPU capacity, zero upgrade surge, labels, control-plane exposure, private invoker and queue bounds |
| Kustomize | One-node and two-node overlays render; assertions check replica counts, placement constraints and private Services |
| Ray SDK | Both Serve configurations validate against Ray 2.59.0; application imports |
| Adapter boundaries | Chunked body over 32 KiB and malformed JSON rejected before forwarding |
| Upstream identities | CPU image tags/digests verified through Docker Hub API; model revision checked against publisher API |
| Containers / model / cluster | Not run; Docker Linux engine unavailable in this environment |
| Hosted workflow / Linux Ray fixture | Assets prepared; not run until the branch is submitted |
| GCP provisioning / IAM / expiry / billing | Not executed |

Meaningful red/green evidence exists for lifecycle corrections, request validation and later integration regressions. The benchmark's first failure was a missing module, which is setup evidence, not a behavioral red phase. Its final HTTP fixtures passed. Windows sandbox restrictions stalled asyncio/local networking checks; the complete offline suite passed outside the sandbox. Pulumi mocks are isolated because their event-loop ownership interferes with unrelated async tests in a single process.

Independent review completed with no remaining blocking preparation findings. Its node-pool finding was corrected: the session uses only one inline CPU pool and omits the conflicting default-pool initial count. The corrected Pulumi contract passes. Integration also corrected the Cloud Tasks token audience to the service origin and requests a full task view when verifying duplicates.

Activation must still establish model/image/memory/CPU fit, KubeRay CRD/chart compatibility, actual scheduling and routing, measured inference, a current cost estimate, cloud expiry and verified deletion. No portfolio performance result is claimed by this preparation.
