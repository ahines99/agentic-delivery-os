# ADR-034: Product Ops handoff and constrained documentation execution

Status: implemented; exact human approval and live PER-8 admission/execution observed through
PR #9's push endpoint on 2026-09-30. Since 2026-10-01 the only admission path is the Linear
monitor's pull intake ([ADR-038](ADR-038-product-ops-pull-intake.md)); the push endpoint was
not carried forward. The lane has not yet run live behind pull intake.

Product Ops defines and publishes approved Linear work. Delivery owns execution and its own
database. An issue label or webhook is notification, not approval. A generated ticket that passes
the pickup contract and carries a `Handoff:` digest is fetched by the Linear monitor from the
configured Product Ops endpoint and admitted through `integrations.product_ops.admit` with no
operator actor; the pinned signature is the authority and the inbox records
`admitted_by: product-ops-monitor`. Admission requires the pinned issuer/key/workspace/policy/
repository scope, the expected specification digest from the ticket, a valid signed public v2
envelope, and complete publication/dispatch evidence. The generated Linear issue is read and
compared before transactional inbox/work/start/outbox creation. Duplicate admission queues only
one start. Changed revisions conflict until explicit downstream revision invalidation exists.
The initial adapter rejects multi-item DAGs atomically.

`admit` keeps its optional `actor` parameter: an authenticated caller is still authorized as an
operator for the repository. No HTTP route passes one today. PR #9's
`POST /handoffs/product-ops` is replaced by pull intake rather than ported.

The public verifier, schema and inert-document capability are vendored from Product Ops's public
contract package under their MIT license. They import no Product Ops implementation or storage.
The original reference consumer's SQLite persistence is not used. Trust remains a Delivery
configuration choice, with no automatic acceptance of unknown policy versions.

A documentation capability binds complete source/requirements/criteria/context semantics,
repository, pinned base, exact plain Markdown path and content. Its canonical digest is the
signed approval's policy version. This permits the exact plan to be approved once in Product Ops
and recognized by Delivery, provided the named approver remains a configured Delivery reviewer
and explicitly appears in the documentation trust list. It does not waive the generic software
lane's independent plan approval. The generic risk policy and builder remain unchanged.

The documentation dispatcher rechecks current configuration, reviewer, approval expiry, signed
handoff, pending cancellation and exact generated ticket before creating a review branch. It
uses a deterministic Git commit, isolated index and empty hooks directory. No checkout, filters,
repo code, builder model, target tests, push, merge or status mutation is performed. An atomic
ref transaction verifies the pinned base before adding a dedicated review ref. Exact blob bytes
and the one-addition tree diff must match the installed capability.

Delivery persists an immutable OPEN/UNMERGED local change request artifact with human-only merge
and `auto_merge=false`, and projects HUMAN_REVIEW in its database. The lane records only legal
`domain.lifecycle` edges, because the store rejects any other projection: INGESTED, ANALYZING,
READY, PLANNING and IMPLEMENTING after the authority check; VALIDATING once the review commit
exists; then PR_OPEN (the local change request, not a GitHub PR), REVIEWING and
ACCEPTANCE_CHECK for the deterministic exact-bytes and one-addition checks; then HUMAN_REVIEW.
Each step has a fixed sequence and reason, so an interrupted run resumes by exact replay. A local
change request is not a GitHub PR. Hosted PR publication remains the existing GitHub App
capability and is outside this narrow executor. The executor spends no model budget.

The dispatcher routes by the admitted work type. `admit` derives `documentation_addition` only
from a signed `doc-add-v1-` policy version; such a start command drains Delivery's existing
transactional outbox directly into this lane. It does not start a second general-agent Temporal
planning cycle for an already exact constrained plan, and the generic intake policy would block
that work type anyway. Software tickets, including pull-admitted Product Ops software work,
continue through the existing Temporal workflow. The lane itself refuses any run that is not a
Product Ops `documentation_addition`. DO-4 progress reporting finds the generated ticket through
the inbox `linear_issue_id` and reports the run as in progress, then "in review" once it reaches
HUMAN_REVIEW without a hosted PR. The Product Ops integration does not import protected
qualification corpora, reference answers or evaluation journals.

Update, 2026-10-01: three changes make the lane safe for the first end-to-end run.

- **Repository mapping.** Product Ops names a local repository in its signed specification by a
  path-derived ID (`repo-` plus 32 hex characters), not by name. The repository setting
  `product_ops_repository_ids` maps such IDs to the configured repository, for both the verifier
  and admission. The lane also rechecks that the signed work item still maps to the run's
  repository. An ID may map to only one repository, and the setting is excluded from the
  execution digest.
- **Final refusals.** An authority failure (expired or changed approval, revoked reviewer,
  changed ticket or configuration) ends the run once as `POLICY_BLOCKED`, or as `CANCELLED` for
  an authenticated cancellation. The start command is rejected and is not retried. Transient
  failures, such as git or disk errors, still retry.
- **Open reviews hold the repository.** A completed lane run leaves a local review branch, not a
  hosted PR. The ADR-033 busy check now also treats the repository as busy while such a branch
  exists and its head is not in the base branch. Deleting or merging the branch releases it, and
  an unreadable review record fails closed.

Known limits: local single-repository review only; no DAG execution, automatic revision replacement,
cross-system cancellation push, hosted PR or merge in this path. Signed exports have bounded lifetimes; disconnected consumers
cannot promise instantaneous producer-side revocation. Local configuration and generated-ticket
currentness are checked at dispatch, and expired exports hold.
