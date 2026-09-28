# Security model

Status: target contract for the staged implementation, not a claim that the foundation already enforces every control. External integrations and arbitrary code execution remain disabled until their milestone gates pass. Research basis: [security review](research/03-security-review.md), accessed 2026-09-27.

## Scope and invariant

The MVP accepts operator-configured Python repositories and Tier 0/1 tasks in a single-tenant local environment. Tier 2/3 work pauses for human handling; unknown risk fails closed. Every tier requires human merge. No model, agent role, publisher, or orchestrator gets an agent-callable merge/deploy capability. Ticket completion is observed after human merge and any required deployment evidence, never inferred from a successful builder run.

Policy enforcement precedes tool registration and execution. A prompt can request an operation but cannot grant a permission. The trusted policy service evaluates actor, run, repository, immutable inputs, risk, workflow state, permitted capability, arguments, quota, and approval context for each operation. Recheck immediately before a side effect and persist the decision. The same checks apply to retries and administrative resumes.

## Trust boundaries

| Boundary | Trusted responsibilities | Untrusted inputs and required guard |
| --- | --- | --- |
| Public ingress -> control plane | Authenticate delivery, authorize workspace/repository, durable inbox | Limit body size/rate; verify bytes before parsing; no model calls inside HTTP receipt handling. |
| Control plane -> model | Minimize/redact context; enforce schemas and budgets | Model responses are proposals. They cannot change policies, actor identity, evidence, or approval state. |
| Control plane -> execution host | Admit fixed sandbox profile; set time/resource limits | Never interpolate repository-supplied container arguments, host paths, images, or runtime settings. |
| Host -> builder sandbox | Provide pinned snapshot and bounded writable workspace | All repository code, test plugins, dependencies, Git metadata, and scripts are untrusted executable content. |
| Sandbox -> artifact collector | Read bounded outputs into quarantine | Canonicalize paths; reject traversal, external symlinks, devices, oversized archives/files, and unexpected executable hooks. Never run collection helpers from the target repository. |
| Artifact -> publisher | Independently validate exact patch/head and publish permitted branch/PR | No sandbox credential forwarding. Publisher never executes build scripts or target Git hooks. |
| Evidence -> reviewer/human | Verify provenance and show complete uncertainty | Escape active markup; avoid fabricated passes; no acceptance based on model confidence alone. |
| Human -> approval API | Authenticate/authorize actor; record exact reviewed context | A claimed username or webhook comment is not approval authentication. Browser flows require CSRF protection and session controls. |

Do not allow ticket URLs to select clone destinations, internal endpoints, or arbitrary linked-document fetches. Resolve provider IDs through configured mappings; validate allowed HTTPS hosts, redirects, and resolved addresses when fetching approved external references. Block loopback, private, link-local, and metadata endpoints. Maintain explicit tenant/workspace ownership checks even in the single-tenant prototype.

## Webhook authentication, replay, and recovery

1. Enforce HTTPS in connected mode; bound request size and parsing time. Keep signing secrets in the control plane and permit a bounded key-rotation overlap. Never log raw credentials or full sensitive payloads.
2. GitHub: validate the complete raw body against `X-Hub-Signature-256` using HMAC-SHA256, strict format/length checks, and constant-time comparison. Linear: do the equivalent using `Linear-Signature`; after signature validation, parse and require a finite integer `webhookTimestamp` within 60 seconds in either direction using a synchronized clock. A stale first receipt is quarantined/reconciled, not silently admitted.
3. Authorize the configured provider installation/workspace and repository IDs. Allow only subscribed event/action pairs. Do not trust the event header alone to determine payload semantics.
4. Atomically commit a durable inbox record and scheduling/outbox record before acknowledging. Unique key: `(provider, integration_id, delivery_id)`; also track signed raw-body digest and semantic resource/version keys. Store receipt state separately from processing state. An authenticated duplicate returns success; an infrastructure failure before durable receipt returns a retryable failure.
5. Enqueue once; use lease/version checks and idempotency keys for downstream actions. An internal retry references the verified stored event and does not rerun freshness checks against the later processing time. Retain deduplication metadata for at least 30 days; this is a project retention choice, not a proof against all old replay.
6. Delivery IDs are unsigned headers. A changed ID with identical signed bytes must not duplicate side effects. For GitHub, no universal signed freshness timestamp exists; reconcile current provider state and enforce head/version preconditions. After deduplication retention expires, replay still cannot recreate a completed transition or authorize a new action. New workflow attempts require an explicit authenticated request and new attempt identity.
7. Missed, stale, or out-of-order events trigger authenticated reconciliation jobs. Never rewind merged/cancelled state based on an old webhook. Verify provider retry timestamp behavior in integration fixtures and recorded deliveries; do not widen the freshness window simply to hide ingestion outages.

The signature and provider delivery details come from [GitHub](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries) and [Linear](https://linear.app/developers/webhooks); deduplication and recovery choices above are project policy.

## Credentials and publication

Store GitHub App private keys, webhook secrets, issue-tracker tokens, and model API keys outside the execution sandbox. The builder has no production credentials, no GitHub token, no model-provider key, no credential helper, and no access to the broker network. It produces filesystem/patch artifacts. Model tool requests run through the control plane; the offline sandbox never calls the model directly.

The broker obtains short-lived GitHub installation credentials limited to the exact configured repository and required operation. Fetch can use a read-only identity; publishing uses narrowly scoped contents/PR access. Tokens remain in broker memory or a protected ephemeral credential channel and are redacted from process arguments, logs, artifacts, caches, and Git remotes. Expiry or revocation stops/retries safely; never fall back to an operator PAT. [GitHub installation authentication](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app).

The publisher reconstructs permitted commits from validated artifacts in its own clean checkout, disables repository hooks and external Git helpers, rejects unexpected submodules/LFS operations, checks the destination and exact ref, and restricts writes to `agent/<work-item>/<attempt>`. Branch-prefix checks are application policy, not a claimed GitHub token scope. Remove application bypass rights from protected branches. Disallow changes to workflows, policy, sandbox definitions, ownership, and credentials in Tier 0/1; reclassify and pause if discovered after build.

Repository write permissions may allow more than branch creation. Defense therefore combines a broker API that exposes no merge operation, protected-branch rules, no bypass actor, restricted credentials, and tests against direct ref updates. Human merges occur through GitHub under required checks/reviews. Administrative bypass remains a separately governed human capability; the application cannot prove security against a compromised repository administrator.

## Approval and evidence integrity

An approval record includes `repository_id`, `pull_request_id`, `head_sha`, `base_sha`, `criteria_digest`, `policy_digest`, `evidence_digest`, `approval_kind`, authenticated `approver_id`, `approved_at`, and `expires_at`. Plan approvals also bind the plan digest. The exact tuple must match at admission. Rebase, force push, new commit, material base change, changed criteria/policy, expired approval, missing evidence, or revoked reviewer access invalidates readiness.

The builder cannot write authoritative evidence or approval records. The test runner signs or authenticates its own result envelope with run ID, command/profile, image digest, snapshot/head, exit code, test counts, durations, artifact digests, and outcome. Treat failed, skipped, flaky, and not-run checks explicitly. A zero exit code with no expected tests is not a pass. Collection hashes establish identity, not correctness; models still review test adequacy and humans assess residual uncertainty.

Independent review uses fresh context, immutable requirements, diff, base/head snapshots, and original test outputs. It receives no hidden builder reasoning and cannot approve itself into a more privileged tool role. Repository `AGENTS.md`, comments, and reports are data when reviewing a target repository, never authority to amend platform policy. Agent review is advisory and never substitutes for human approval.

## Sandbox and data handling

Apply [ADR-003](adr/ADR-003-sandbox-policy.md) before execution. Compose infrastructure is not a sandbox and must not share control-plane secrets or its network with builder jobs. Enforce maximum elapsed time, CPU/memory/process/output/disk budgets, cancellation, and teardown. Do not put private repository content into an external model without configured operator authorization for that provider and data class.

Keep audit metadata append-only through the application, including actor, policy version, decisions, transition versions, and artifact references. Local database rows are not tamper-proof against a host administrator; production tamper evidence requires protected external storage and key management. Redact secrets before logs and artifact export. Default artifact retention is 30 days; allow explicit shorter retention for sensitive repositories. Separate minimal audit metadata retention from raw source/test output retention. Deletion/revocation must remove stale caches and queued capabilities.

## Adversarial release gates

These are required tests for connected execution releases; scaffold unit tests alone do not satisfy them.

| Attack or failure | Required observable result |
| --- | --- |
| Missing/malformed/incorrect signature; altered Unicode body; oversized JSON | Reject before any workflow or external write; no credential leakage. |
| Stale/future Linear timestamp; replay with changed delivery ID; concurrent duplicate | No duplicate workflow/PR/comment; explicit stale handling and durable inbox proof. |
| Crash after inbox commit; crash after external PR creation; old event after cancellation | Recover without double effect or state rewind, using provider reconciliation/idempotency. |
| Wrong workspace/installation/repository; arbitrary clone URL; metadata URL/redirect | Deny with recorded reason before fetch or execution. |
| Ticket/README/test output instructs secret upload, policy change, or merge | Tool admission refuses; audit records attempt; secret remains inaccessible. |
| Malicious Git hook, pytest plugin, setup script, symlink, archive traversal | Confined to sandbox; publisher/collector execute no repository-controlled helper. |
| Attempt host/Docker socket access, metadata egress, DNS/IPv6/raw-socket egress | Denied by actual runtime controls; packet/runtime evidence retained. |
| Fork bomb, output flood, disk exhaustion, timeout, cancel during execution | Job terminated within defined limit; host remains responsive; no orphan resources. |
| Builder forges PASS evidence or modifies test runner report | Provenance check fails; acceptance stays unverified. |
| New head/base/policy/criteria after approval; reviewer is builder | Readiness revoked and fresh independent/human review required. |
| Agent tries merge, protected ref push, ruleset edit, broader token scope | Denied across broker and provider boundaries; no remote mutation. |
| Expired token, disabled installation, provider outage, secret rotation | Fail closed or bounded retry; no privilege escalation/fallback credential. |

Expand the threat model before multi-tenant hosting, arbitrary repositories, sensitive data, infrastructure changes, or automated release work. Any failed gate disables that capability until fixed and rerun.
