# Lab working agreement

- CPU-only GKE is the accepted first deployment; Slurm, Triton and real GPUs follow separately.
- Work on the current focused branch. Agents own disjoint paths and never change branches or commit independently.
- No cloud provisioning, IAM changes, billing changes, deployment or merges during preparation. The owner reviews the concrete resource plan before activation.
- Use Pulumi Python, separate foundation/session state, explicit project/location/run ownership and bounded node counts. Never target Fleet resources or state.
- Use behavior-first tests for meaningful changes. A missing dependency/import is not a behavior regression.
- Test failure/retry/expiry/cleanup paths and input boundaries. Never replace a required cloud/model experiment with a mocked acceptance claim.
- Keep account identifiers, credentials, raw provider output, state and model weights outside public source. Public PR checks receive no cloud credentials.
- Public services are unnecessary: ClusterIP and operator-controlled access only. Ray management interfaces remain private.
- Record upstream versions, license provenance and reused design patterns. Pin runtime/model revisions and images before activation.
- Keep preparation, local checks, hosted CI, real model execution and cloud acceptance distinct in documentation.
