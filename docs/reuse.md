# Fleet lifecycle provenance

The owner authorized reuse of Ottawa Fleet Platform's lab lifecycle on October 22, 2026. Inspected source revision: `e53a045742dd5b93bf16cebaa964632ab36b416c`.

References: `scripts/ci_lab.py`, `scripts/lab_cleanup.py`, `scripts/cleanup_execute.py`, `functions/lab_shutdown/main.py` and `.github/workflows/lab-deploy.yml` in `ottawa-fleet-platform`.

Reused design: durable expiry registered before provisioning; fixed session deadline; exact project/location/session ownership; retries until cleanup is verified; private provider evidence; credentials-free PR checks; explicit retained-cost inventory. Implementation here is original Python/Pulumi code adapted to a GKE-only disposable session. No Fleet state, identifiers, credentials, application/database resources or Terraform modules were copied. No repository license was found in that inspected checkout, so this is pattern reuse under the owner's instruction, not redistribution of its source.

This smaller preparation does not yet reproduce Fleet's durable cloud lease/Cloud Build orchestration. Local immutable session records, Pulumi stack locking and unique GKE names constrain overlap. Cloud Tasks retries a temporarily missing cluster through a grace window to cover creation races. That window is not a guaranteed billing cutoff. Live expiry, interrupted provisioning and stale state recovery are required activation evidence.

Pinned upstream candidates checked October 22, 2026:

| Asset | Selected identity | License/source |
| --- | --- | --- |
| Ray CPU | `2.59.0-py312-cpu`, digest `sha256:0ffca209fb4c984d648db550b8dbe7879bdba3bbb5d96ee5894843cf6ac12eb5` | [Ray Apache-2.0](https://github.com/ray-project/ray) |
| vLLM CPU | `v0.27.1-x86_64`, digest `sha256:0314b8a7594a3fc54e8a0c3ca1ba0c9257302bfb546abfb49a2d6107d2d0767f` | [vLLM Apache-2.0](https://github.com/vllm-project/vllm) |
| Qwen3-0.6B | revision `c1899de289a04d12100db370d81485cdf75e47ca` | [Publisher model/license](https://huggingface.co/Qwen/Qwen3-0.6B) |
| KubeRay operator | chart `1.7.1` (activation must verify downloaded chart) | [KubeRay Apache-2.0](https://github.com/ray-project/kuberay) |
| Pulumi / GCP SDK | Python `pulumi==3.271.0`, `pulumi-gcp==10.2.0` | [Pulumi Apache-2.0](https://github.com/pulumi/pulumi), [GCP provider Apache-2.0](https://github.com/pulumi/pulumi-gcp) |

Image-tag existence and model revision verification do not establish runtime compatibility. Containers bundle additional dependencies and licenses. New custom Ray/expiry images must be built, checked and pinned by digest during activation. No model weights are committed.
