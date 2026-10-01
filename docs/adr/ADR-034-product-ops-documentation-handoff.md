# ADR-034: Product Ops handoff and constrained documentation execution

Status: implemented; exact human approval and live PER-8 admission/execution observed.

Product Ops defines and publishes approved Linear work. Delivery owns execution and its own
database. An issue label or webhook is notification, not approval. `POST /handoffs/product-ops`
requires operator authentication, pinned issuer/key/workspace/policy/repository scope, an expected
specification digest, a valid signed public v2 envelope, and complete publication/dispatch evidence.
The generated Linear issue is read and compared before transactional inbox/work/start/outbox
creation. Duplicate admission queues only one start. Changed revisions conflict until explicit
downstream revision invalidation exists. The initial adapter rejects multi-item DAGs atomically.

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
Each step has a fixed sequence and reason, so an interrupted run resumes by exact replay. A local change request is
not a GitHub PR. Hosted PR publication remains the existing GitHub App capability and is outside
this narrow executor. The executor spends no model budget.

The short documentation path drains Delivery's existing transactional outbox directly. It does
not start a second general-agent Temporal planning cycle for an already exact constrained plan.
Software tickets continue through the existing Temporal workflow. The Product Ops integration
does not import protected qualification corpora, reference answers or evaluation journals.

Known limits: local single-repository review only; no DAG execution, automatic revision replacement,
cross-system cancellation push, hosted PR or merge in this path. Signed exports have bounded
lifetimes; disconnected consumers cannot promise instantaneous producer-side revocation. Local
configuration and generated-ticket currentness are checked at dispatch, and expired exports hold.
