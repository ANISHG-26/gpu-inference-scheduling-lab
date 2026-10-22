# GCP trial and first-session estimate

Research refreshed October 22, 2026. Project count is an account/organization quota, not a universal ten-project trial entitlement. Creating a separate project provides an independent resource/IAM boundary; it does not multiply a billing account's credit balance or free-tier allowances. [Project quota guidance](https://docs.cloud.google.com/resource-manager/docs/creating-managing-projects#managing_project_quotas).

The trial terms restrict Compute Engine to eight concurrently used cores. Live project quotas can display different numeric limits; the deployment still follows the trial terms. Keep the first session to one four-vCPU node and account for other projects before trying two nodes. GPU quota was zero during this activation preflight. No billing upgrade or quota increase is part of the lab. [Trial terms](https://cloud.google.com/terms/free-trial).

The operator must confirm actual remaining credit and expiry in Billing. An open billing account alone does not prove the account remains on a free trial. Credit and free-tier limits apply across linked projects. Account identifiers and the owner's balance are kept outside this public repository.

## Initial one-node session

At published US-central on-demand rates, `n2-standard-4` is approximately US$0.194236/hour; allow US$0.10/hour for GKE management rather than assuming an unused free-tier allowance. Two hours therefore gives about US$0.59 for these two items. Add 30 GB of standard boot disk, one ephemeral external IPv4, small API/logging usage, image build time and stored image/source artifacts. Budgetary expectation for this initial two-hour activation is under US$2 with small build/transfer volumes; this is an estimate, not an enforced billing cap. CAD billing follows Google's applicable currency SKUs. [VM prices](https://cloud.google.com/products/compute/pricing/general-purpose?hl=en), [GKE pricing](https://cloud.google.com/kubernetes-engine/pricing), [network prices](https://cloud.google.com/vpc/network-pricing), [registry prices](https://cloud.google.com/artifact-registry/pricing).

Docker Desktop did not start on the operator's machine. A dedicated Cloud Build identity can build the images using only the allowed source files. Source objects use a private bucket with a one-day deletion lifecycle; images remain in Artifact Registry until explicitly removed. The build configuration uses Cloud Logging and a bounded build timeout. The bucket and identity belong to the Pulumi foundation.

Cluster expiry removes the temporary GKE session. It retains the foundation, registry images, private build-source bucket, queue and scale-to-zero expiry endpoint. Inventory retained storage and logs after shutdown. Do not treat a successful delete request or a budget alert as proof that all costs have stopped.
