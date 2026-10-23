# Sequential CPU lessons

Use one lesson per disposable session. The operator console observes only the configured active lesson; selecting a page never deploys a stack. Its current action adapter is the fixed inference Service. Slurm and Triton are preparation material until their [compatibility gates](../docs/lesson-compatibility.md) pass.

| Lesson | Entrypoint | Evidence boundary |
| --- | --- | --- |
| [01: single node](01-single-node-inference/README.md) | `k8s/base` | Real inference/load/recovery validated; console exercised in the browser |
| [02: two nodes](02-two-node-inference/README.md) | `k8s/two-nodes` | Real placement/load/recovery validated through the console API; fresh browser verification remains |
| [03: Slurm CPU](03-slurm-cpu-scheduling/README.md) | Upstream Slinky evaluation | Packaging and live adapter blocked |
| [04: Triton CPU](04-triton-cpu-serving/README.md) | Deterministic teaching model inputs | Runtime/image selection and live adapter blocked |

Shared lifecycle remains in `infra/foundation`, `infra/session`, and `src/inference_lab`. Existing CLI commands and Kustomize entrypoints are preserved. Shared console assets live in `operator/`, with deployment inputs in `k8s/operator/`. The small `inference_lab.lessons` catalog supplies console teaching text; these READMEs record operator procedures and acceptance evidence.

Before each focused session: review its resource plan, prove the previous session absent, register immutable expiry through the existing lifecycle, deploy exactly one lesson, then open the localhost console. Predictions precede experiments; observations precede conclusions. A fixture pass never marks a lesson measured.
