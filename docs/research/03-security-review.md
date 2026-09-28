# Security and execution review

Research date: 2026-09-27. This review turns the supplied blueprint into implementation decisions; it does not certify the scaffold as a secure execution service.

## Findings and decisions

| Blueprint gap | Final decision | Release gate |
| --- | --- | --- |
| Security and policy arrive after execution in the proposed roadmap. | Implement deny-by-default tool authorization, repository allowlisting, audit records, and sandbox admission before running repository code. | A denied request executes no tool and creates no external side effect. |
| A merge/release agent and a generic `merge()` adapter conflict with human control. | No agent can merge at any tier. Omit merge and deployment actions from agent capabilities. Humans merge in GitHub. | Builder, reviewer, publisher, and workflow retries cannot call merge or directly update protected branches. |
| Container isolation and `network_policy: restricted` are underspecified. | Local Docker is a trusted-operator, single-tenant prototype boundary. Start offline; stronger remote isolation requires a separate decision and adversarial validation. | Prove network denial, resource termination, host isolation, and teardown on the actual runtime. |
| Branch pushing implies secret access inside execution. | A trusted publisher handles immutable patch/commit artifacts; installation tokens stay outside the sandbox. | Malicious setup scripts, Git hooks, and tests cannot read broker credentials. |
| Approval is treated as a boolean. | Bind it to repository, PR, head/base, criteria, policy, evidence, approver, and expiration. | New commits, changed requirements, or changed policy invalidate approval. |
| Independent prompts are treated as independent controls. | Separate capabilities and fresh review context; deterministic admission validates evidence provenance. | Builder-authored claims cannot mint successful test evidence or approvals. |

## Verified provider behavior

GitHub signs raw webhook bodies using HMAC-SHA256 in `X-Hub-Signature-256`. Verify before using payload data, with constant-time comparison. [GitHub signature documentation](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries) (accessed 2026-09-27).

GitHub reuses `X-GitHub-Delivery` for redeliveries and recommends short webhook response times. It does not automatically redeliver failures. These facts require durable receipt storage plus explicit recovery, rather than assuming automatic at-least-once delivery. [Webhook best practices](https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks), [redelivery documentation](https://docs.github.com/en/webhooks/testing-and-troubleshooting-webhooks/redelivering-webhooks) (accessed 2026-09-27).

Linear supplies a raw-body HMAC-SHA256 signature, delivery UUID, and signed-body `webhookTimestamp` in milliseconds; its guidance checks a one-minute freshness window. Failed deliveries have bounded retries. The consumer must distinguish receipt acknowledgement from successful business processing. [Linear webhooks](https://linear.app/developers/webhooks) (accessed 2026-09-27).

GitHub installation tokens expire after one hour and can be narrowed to repositories and permissions at creation. Treat tokens as opaque strings; the documentation describes a newer token format. [Installation token documentation](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app) (accessed 2026-09-27).

Docker documents the power of daemon access and host mounts. Rootless mode reduces daemon/runtime privilege; it does not make hostile shared-kernel workloads equivalent to separate virtual machines. `--network none` creates only loopback inside the container. [Engine security](https://docs.docker.com/engine/security/), [rootless mode](https://docs.docker.com/engine/security/rootless/), [none network driver](https://docs.docker.com/engine/network/drivers/none/) (accessed 2026-09-27).

GitHub rulesets can dismiss stale reviews and require approval of the latest reviewable push. Configure required human reviews and trusted checks with no application bypass. Repository/organization capabilities must be verified for the selected hosting plan before enabling publishing. [Available ruleset rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets) (accessed 2026-09-27).

## Design inferences and limitations

The provider signature covers the body, not arbitrary delivery headers. Therefore a delivery-ID database alone is not cryptographic replay protection. Add body-digest deduplication, resource/version idempotency, and authenticated provider reconciliation before consequential actions. GitHub has no general equivalent of Linear's signed delivery timestamp; do not invent a universal timestamp check for GitHub.

An HTTP signature proves origin and integrity, not authorization to execute ticket instructions. Repository content, tracker prose, comments, artifacts, and model output remain untrusted data. Commands approved by name can execute arbitrary code through Python imports, test discovery, installation scripts, Git configuration, or plugins; actual confinement belongs at the process boundary.

The relevant threat model is accidental or induced malicious behavior within an operator-approved repository. Running arbitrary public repositories or mutually hostile tenants is excluded from the Docker MVP. A separate disposable VM or stronger sandbox design, independent review, and host/runtime tests are prerequisites to expand that scope.

See [the security model](../security-model.md), [separation of duties](../adr/ADR-002-separation-of-duties.md), and [sandbox policy](../adr/ADR-003-sandbox-policy.md) for enforceable requirements and adversarial release gates.
