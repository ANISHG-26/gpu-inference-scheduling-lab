# Delivery evidence

Updated October 22, 2026. Related delivery: issue #1, merged PR #2 and activation fixes in PR #3. The owner authorized deployment and merging once CI passes. Account identifiers, credentials, provider logs and Pulumi state remain private.

| Evidence | Result |
| --- | --- |
| Standard library behavior suite | 34 tests passed, including actual local HTTP success/error/timeout fixtures and Cloud Tasks request-envelope regression |
| Pulumi resource mock | Passed in an isolated process; checks CPU capacity, zonal placement, zero upgrade surge, labels, control-plane exposure, private invoker and queue bounds |
| Kustomize / operator CRD | Both overlays render and validate against the checksum-verified KubeRay 1.7.1 chart's actual RayService CRD |
| Ray SDK | Both Serve configurations validate against Ray 2.59.0; application imports |
| Adapter boundaries | Four tests pass, including the frozen ASGI route, chunked body over 32 KiB and malformed JSON rejection |
| Upstream identities | CPU image tags/digests verified through Docker Hub API; model revision checked against publisher API |
| Containers | Both custom Linux images built successfully in Cloud Build; GitHub CI also builds both and checks non-root Ray application import |
| Hosted Linux integration | All five checks passed at `0ec0b42`, including actual Ray Serve to HTTP fixture, both builds and pinned vLLM image CLI validation |
| Foundation | Separate project, private network, registry, private source bucket, scoped identities, Cloud Tasks queue and IAM-private Cloud Run service deployed with Pulumi |
| Expiry authentication | Unauthenticated calls denied; authenticated malformed payload rejected; real Cloud Tasks OIDC probe reached the missing-cluster retry path and its probe task was removed |
| First GKE session | One node running; expiry task registered before creation, original two-hour deadline preserved through retries |
| Real model / measured inference | AVX512 verified, model healthy as UID 1000, real generation through Ray and 32/32 bounded load requests succeeded; [measurements](results/2026-10-22-cpu-baseline.md) |
| Model recovery | Exact model pod deleted; replacement UID/Ready and real generation verified after about 182 seconds, with seven timed-out probes during the outage |
| Verified expiry | Pending; do not infer this from fixture or probe success |

Meaningful red/green evidence exists for lifecycle corrections, request validation and later integration regressions. The benchmark's first failure was a missing module, which is setup evidence, not a behavioral red phase. Its final HTTP fixtures passed. Windows sandbox restrictions stalled asyncio/local networking checks; the complete offline suite passed outside the sandbox. Pulumi mocks are isolated because their event-loop ownership interferes with unrelated async tests in a single process.

Independent review completed with no remaining blocking preparation findings. The session uses only one inline CPU pool and omits the conflicting default-pool initial count. Activation exposed additional defects: Cloud Build's legacy builder required a writable Ray work directory and explicit numeric copy group; Cloud Tasks required its REST `task` request envelope; the Pulumi GCP provider rejected the primary zone in its additional `node_locations` field. These corrections have regression checks and independent review. RayService also enables shared token authentication supported by the pinned operator/runtime. The Cloud Tasks audience uses the service origin, with full task view when verifying duplicates.

Live activation established model/image/CPU fit, real scheduling/routing, bounded one-node inference measurements and model-pod recovery. The model's roughly 7.23 GiB startup peak remains close enough to its 8 GiB limit to require bounded workloads. The Ray head needed a 2 GiB limit to avoid controller memory kills; its reservation stays 1 GiB. Cloud expiry and backing-resource absence still need evidence. The [trial and cost notes](gcp-trial.md) record the first-session estimate and restrictions. No GPU or multi-node scaling result is claimed. Mocks and fixtures do not establish provider behavior, IAM propagation or model compatibility.
