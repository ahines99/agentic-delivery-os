# Agentic Delivery OS
## Repository Handoff and Implementation Blueprint

**Working name:** Agentic Delivery OS
**Suggested repository:** `agentic-delivery-os`
**Project type:** Large-scale portfolio project / production-style multi-agent engineering platform
**Primary thesis:** A governed agentic workforce should be able to accept real work from an issue tracker, execute it in an isolated environment, produce a pull request, independently verify the work, identify regressions, request clarification when necessary, and return auditable evidence to a human reviewer.

---

# 1. Executive Summary

Agentic Delivery OS is a governed multi-agent execution platform for software, data, and analytical work.

A ticket enters from Linear, Jira, GitHub Issues, or an upstream operating system. The platform determines whether the work is sufficiently specified, classifies risk, selects an appropriate worker profile, provisions an isolated execution environment, plans the change, implements it, runs validation, opens a pull request, and triggers independent review agents.

The system does not treat "the code compiled" or "the agent says it is done" as completion.

Completion requires evidence that:

1. The original ticket acceptance criteria are satisfied.
2. Relevant tests pass.
3. New tests cover the changed behavior.
4. Unrelated functionality was not materially impacted.
5. Security and policy checks pass.
6. The implementation is traceable to requirements.
7. A human receives a concise, reviewable evidence package.
8. High-risk changes cannot merge without explicit human approval.

The project should support multiple worker personas:

- Software Engineer
- AI Engineer
- Data Engineer
- Analytics Engineer
- Data Scientist
- Analyst
- QA / Test Engineer
- Security Reviewer
- Code Reviewer
- Product / Requirements Analyst

The long-term vision is not "an autonomous coding bot." It is a software delivery control plane for an agentic technical workforce.

---

# 2. Naming Recommendation

## Recommended umbrella name: Agentic Delivery OS

This is stronger than "Agentic Analyst" because the platform is not limited to analytical work.

The platform coordinates several specialized workers, so the product can expose roles such as:

- Agentic Software Engineer
- Agentic AI Engineer
- Agentic Data Engineer
- Agentic Analyst
- Agentic Reviewer
- Agentic QA Engineer

The umbrella product remains **Agentic Delivery OS**.

Alternative names:

- Agentic Execution OS
- Agentic Engineering OS
- Autonomous Delivery Control Plane
- Agentic Technical Workforce
- Agentic Workbench

Avoid making the repository name too narrow. "Agentic Analyst" would undersell the system once it is modifying application code, infrastructure, data models, pipelines, tests, and documentation.

---

# 3. Portfolio Story

The project should demonstrate five capabilities simultaneously.

## 3.1 Product judgment

The system understands that ambiguous tickets should not be implemented blindly.

It can pause work and ask:

- What behavior is expected?
- Which users are affected?
- What is the rollback path?
- Are there permission implications?
- What are the acceptance criteria?
- Does this require a migration?
- Is the requested behavior backward-compatible?

## 3.2 Production AI engineering

The system coordinates multiple agents, tool access, context retrieval, execution sandboxes, repository operations, evaluations, and durable workflows.

## 3.3 Software engineering controls

The system uses:

- Branch isolation
- Pull requests
- CI
- Tests
- Linting
- Type checks
- Policy checks
- Rollback procedures
- Human approval gates
- Audit logs

## 3.4 Evaluation rigor

The project measures whether agents actually complete work correctly.

It should be evaluated against historical tickets where an accepted human implementation is already known.

## 3.5 Enterprise governance

The system applies different autonomy levels based on change risk.

It should be safe for a company to say:

"Agents may independently create pull requests, but production merges and sensitive changes remain governed."

---

# 4. Core Product Flow

```text
Ticket Created / Assigned
        |
        v
Ingestion + Normalization
        |
        v
Requirements Analysis
        |
        +----> Insufficient requirements -> BLOCKED / Clarification Request
        |
        v
Risk Classification
        |
        v
Worker Selection
        |
        v
Repository Context Build
        |
        v
Implementation Plan
        |
        +----> Human plan approval if policy requires
        |
        v
Sandbox Provisioning
        |
        v
Implementation
        |
        v
Local Validation
        |
        v
Pull Request Creation
        |
        v
Independent Review
        |
        +----> Change requests -> Builder correction loop
        |
        v
Acceptance-Criteria Verification
        |
        v
Regression / Impact Analysis
        |
        v
Security / Policy Review
        |
        v
Human Review Gate
        |
        v
Merge
        |
        v
Deployment Verification
        |
        v
Ticket Complete + Evidence Package
```

---

# 5. Supported Work Types

The first production-quality version should support distinct work classes.

## 5.1 Software engineering

Examples:

- Add an API endpoint
- Fix application behavior
- Refactor a service
- Implement a UI feature
- Add authentication-compatible functionality
- Upgrade a dependency
- Add tests
- Improve error handling

## 5.2 AI engineering

Examples:

- Add a retrieval pipeline
- Build an agent tool
- Modify prompt orchestration
- Add model evaluation
- Add fallback behavior
- Add structured outputs
- Build an inference service
- Add tracing / observability

## 5.3 Data engineering

Examples:

- Add a source connector
- Build an ingestion pipeline
- Add incremental loading
- Update a dbt model
- Add quality tests
- Modify orchestration
- Add lineage metadata
- Repair schema drift

## 5.4 Analytics engineering

Examples:

- Add a metric
- Add a semantic model
- Create a reporting mart
- Add reconciliation logic
- Add a dashboard data contract

## 5.5 Data science

Examples:

- Add a feature pipeline
- Implement a model
- Reproduce an experiment
- Add evaluation
- Add monitoring
- Update a training workflow

## 5.6 Analyst work

Examples:

- Investigate a business question
- Analyze a dataset
- Produce a memo
- Reconcile KPIs
- Diagnose an anomaly
- Build a financial or operational model

Analyst outputs should still be reviewable artifacts with sources, assumptions, and reproducibility.

---

# 6. Agent Architecture

Use specialized agents with separation of duties.

## 6.1 Intake Agent

Responsibilities:

- Parse the incoming ticket.
- Identify repository, branch, service, component, and owner.
- Normalize acceptance criteria.
- Identify linked documents.
- Identify ambiguity.
- Produce a machine-readable work specification.

Output:

```json
{
  "ticket_id": "ENG-142",
  "work_type": "software_engineering",
  "summary": "Add customer status filter",
  "acceptance_criteria": [],
  "dependencies": [],
  "ambiguities": [],
  "risk_signals": [],
  "recommended_worker": "software_engineer"
}
```

## 6.2 Requirements Agent

Responsibilities:

- Determine whether the ticket is implementable.
- Convert prose requirements into explicit acceptance criteria.
- Identify missing decisions.
- Compare ticket requirements with existing repository behavior.
- Reject unsupported assumptions.

Possible outcomes:

- READY
- READY_WITH_ASSUMPTIONS
- NEEDS_CLARIFICATION
- OUT_OF_SCOPE
- POLICY_BLOCKED

The agent must never silently invent critical product requirements.

## 6.3 Risk Classifier

Classify every task before implementation.

### Tier 0: documentation / non-code

Examples:

- Documentation
- Comments
- Test fixtures

### Tier 1: low risk

Examples:

- Isolated UI changes
- Internal tools
- Non-sensitive tests
- Minor application logic

### Tier 2: moderate

Examples:

- API changes
- Data model changes
- Shared business logic
- Non-destructive migrations
- Agent orchestration

### Tier 3: high

Examples:

- Authentication
- Authorization
- Financial calculations
- Payments
- Sensitive data
- Destructive migrations
- Production infrastructure
- Secrets
- Compliance controls
- Security policies

Tier 3 should always require explicit human approval before merge.

## 6.4 Planner Agent

Responsibilities:

- Build a repository-aware implementation plan.
- Identify files likely to change.
- Identify relevant tests.
- Identify downstream dependencies.
- Identify migration requirements.
- Estimate complexity.
- Define rollback approach.

The plan should be persisted as an artifact.

## 6.5 Builder Agent

Responsibilities:

- Work in an isolated branch and sandbox.
- Make repository changes.
- Write or update tests.
- Run local checks.
- Commit changes.
- Produce structured evidence.

The Builder cannot approve its own work.

## 6.6 Test Agent

Responsibilities:

- Determine expected test coverage.
- Run existing targeted tests.
- Run broader regression suites according to risk.
- Generate new tests when acceptance criteria are insufficiently covered.
- Report failing, flaky, skipped, and passing tests independently.

## 6.7 Regression Agent

Responsibilities:

Build a repository impact graph:

```text
changed symbol
    -> callers
    -> modules
    -> services
    -> APIs
    -> data contracts
    -> downstream consumers
    -> tests
```

It should answer:

- What could this change break?
- Which existing behavior depends on changed code?
- Which tests validate that behavior?
- Which additional tests should run?
- Are public interfaces changed?
- Are schemas changed?
- Are data contracts changed?

## 6.8 Reviewer Agent

Fresh context. No privileged access to the Builder's hidden reasoning.

Responsibilities:

- Review the diff.
- Review architecture.
- Detect unnecessary complexity.
- Check repository conventions.
- Check failure cases.
- Check backwards compatibility.
- Check maintainability.
- Check acceptance criteria.

Output:

- APPROVE
- REQUEST_CHANGES
- BLOCK

Every finding should include evidence.

## 6.9 Acceptance Agent

This agent is responsible for ticket-to-evidence traceability.

Example:

| Criterion | Implementation | Verification | Result |
|---|---|---|---|
| AC-1 | `filters.py:42` | `test_status_filter` | PASS |
| AC-2 | pagination unchanged | regression suite | PASS |
| AC-3 | p95 < 500 ms | benchmark | PASS |

The Acceptance Agent should not accept a criterion that has no evidence.

## 6.10 Security Agent

Responsibilities:

- Secret scanning
- Dependency vulnerability review
- Injection risk
- Authorization changes
- Data leakage
- Unsafe logging
- PII handling
- Command execution risks
- Deserialization risks
- Prompt-injection risks for AI systems

Security findings should be severity-ranked.

## 6.11 Merge / Release Agent

Responsibilities:

- Verify required checks.
- Verify required human approvals.
- Merge only if policy allows.
- Monitor deployment status.
- Trigger smoke tests.
- Reopen or rollback if deployment validation fails.

Initially, production merge should remain human-controlled.

---

# 7. Ticket Lifecycle State Machine

Use a durable state machine.

Suggested states:

```text
NEW
INGESTED
ANALYZING
NEEDS_CLARIFICATION
READY
PLANNING
PLAN_REVIEW
IMPLEMENTING
VALIDATING
PR_OPEN
REVIEWING
CHANGES_REQUESTED
ACCEPTANCE_CHECK
HUMAN_REVIEW
APPROVED
MERGED
DEPLOYING
VERIFYING
DONE
FAILED
ROLLED_BACK
CANCELLED
POLICY_BLOCKED
```

Every transition must be logged.

Every state transition should contain:

- actor
- timestamp
- reason
- previous state
- next state
- evidence references
- cost
- model / tool version

---

# 8. Ticket Schema

Normalize Linear, Jira, GitHub Issues, and internal upstream systems into a common schema.

```python
class WorkItem:
    id: str
    source_system: str
    source_url: str
    project: str
    title: str
    description: str
    acceptance_criteria: list[AcceptanceCriterion]
    labels: list[str]
    priority: str
    assignee: str | None
    repository: str
    base_branch: str
    linked_docs: list[str]
    linked_issues: list[str]
    risk_tier: int | None
    worker_profile: str | None
    status: str
```

Acceptance criterion:

```python
class AcceptanceCriterion:
    id: str
    description: str
    verification_type: str
    evidence_required: list[str]
    status: str
```

---

# 9. Integration Architecture

Create provider adapters rather than hard-code vendors.

## Issue trackers

Interface:

```python
class IssueTrackerAdapter:
    async def get_ticket(ticket_id): ...
    async def update_status(ticket_id, status): ...
    async def add_comment(ticket_id, comment): ...
    async def create_subtask(...): ...
```

Implement:

- LinearAdapter first
- JiraAdapter second
- GitHubIssuesAdapter third

## Source control

Interface:

```python
class SourceControlAdapter:
    async def create_branch(...): ...
    async def create_pull_request(...): ...
    async def comment_on_pr(...): ...
    async def request_review(...): ...
    async def merge(...): ...
```

Initial provider:

- GitHub

Future:

- GitLab
- Bitbucket

## Execution environments

Interface:

```python
class ExecutionEnvironment:
    async def provision(...): ...
    async def execute(command): ...
    async def read_file(path): ...
    async def write_file(path, content): ...
    async def collect_artifacts(...): ...
    async def destroy(...): ...
```

Potential implementations:

- Docker local sandbox
- Ephemeral Kubernetes job
- Remote developer environment
- Vendor-specific cloud coding environment

Do not make the core architecture dependent on a single model provider or coding environment.

---

# 10. Model Provider Abstraction

Support multiple model providers.

```python
class ModelClient:
    async def complete(messages, tools, response_schema, config): ...
```

Recommended profiles:

```yaml
profiles:
  planner:
    provider: configurable
    model: configurable
    temperature: low

  builder:
    provider: configurable
    model: configurable
    tool_access: code_execution

  reviewer:
    provider: configurable
    model: configurable
    context_policy: independent

  acceptance:
    provider: configurable
    model: configurable
    structured_output: true
```

The project should compare providers during evaluation, but no workflow should depend on one vendor-specific behavior.

---

# 11. Repository Context System

A central challenge is giving agents enough repository context without dumping the entire repository into every prompt.

Build a repository intelligence layer.

## Sources

- File tree
- README
- architecture docs
- ADRs
- dependency manifests
- code symbols
- import graph
- call graph
- tests
- CI configuration
- schema files
- API specifications
- git history
- CODEOWNERS
- previous PRs
- issue links

## Repository index

Store:

- file metadata
- symbols
- symbol relationships
- embeddings
- dependency relationships
- test mappings
- ownership
- change frequency
- risk classifications

Possible storage:

- PostgreSQL
- pgvector
- optional graph database later

Start with PostgreSQL + pgvector plus explicit relationship tables.

Do not add Neo4j until the relationship complexity justifies it.

---

# 12. Impact Graph

The impact graph is one of the project's differentiators.

Nodes:

- repository
- service
- module
- file
- class
- function
- API endpoint
- event
- database table
- dbt model
- data contract
- job
- test
- package

Edges:

- imports
- calls
- depends_on
- reads
- writes
- exposes
- consumes
- tests
- deploys_with
- owned_by

The Regression Agent should traverse this graph from changed nodes.

Example:

```text
calculate_discount()
    -> QuoteService
    -> InvoiceService
    -> RenewalForecast
    -> /quotes endpoint
    -> pricing_events
    -> revenue_forecast mart
```

A ticket modifying `calculate_discount()` should automatically trigger targeted validation across those surfaces.

---

# 13. Pull Request Evidence Package

Every generated PR should include a structured report.

Template:

```markdown
## Ticket
ENG-142 - Add status filtering to customers

## Implementation summary
...

## Acceptance criteria
- [x] AC-1 ...
- [x] AC-2 ...

## Files changed
...

## Tests added
...

## Tests executed
...

## Regression analysis
...

## Security impact
...

## Database / schema impact
...

## API compatibility
...

## Performance impact
...

## Known limitations
...

## Rollback
...

## Agent review
Builder: completed
Reviewer: approved
Regression: approved
Security: approved
Acceptance: 3/3 satisfied

## Human review requested
...
```

---

# 14. Requirement-to-Test Traceability

Create a first-class database object.

```python
class VerificationEvidence:
    criterion_id: str
    evidence_type: str
    source: str
    result: str
    artifact_uri: str | None
```

Evidence types:

- unit_test
- integration_test
- e2e_test
- benchmark
- screenshot
- static_analysis
- schema_validation
- manual_review
- runtime_observation

No acceptance criterion can be marked satisfied without at least one defined verification method.

---

# 15. Human-in-the-Loop Controls

Humans should intervene at well-defined gates.

Possible gates:

1. Requirements clarification
2. Plan approval
3. Sensitive-data approval
4. High-risk implementation approval
5. Pull request approval
6. Merge approval
7. Production rollback decision

Configuration example:

```yaml
policies:
  risk_tier_0:
    plan_approval: false
    merge_approval: true

  risk_tier_1:
    plan_approval: false
    merge_approval: true

  risk_tier_2:
    plan_approval: optional
    merge_approval: true

  risk_tier_3:
    plan_approval: true
    merge_approval: true
    security_approval: true
```

---

# 16. Durable Orchestration

Do not build the workflow as a single synchronous script.

Use durable orchestration.

Requirements:

- retries
- timeouts
- idempotency
- state persistence
- human pauses
- long-running workflows
- compensating actions
- resumability
- workflow versioning

Reasonable implementation options:

- Temporal
- Prefect
- durable event-driven state machine

Temporal is especially attractive because the workflow may wait hours or days for human review.

---

# 17. Core Services

Suggested service boundaries.

```text
api-service
orchestrator
ticket-service
repo-intelligence-service
execution-service
agent-service
policy-service
evaluation-service
audit-service
notification-service
```

Start as a modular monolith unless scale requires independent deployment.

A strong portfolio project does not need premature microservices.

---

# 18. Suggested Technology Stack

## Backend

- Python 3.12+
- FastAPI
- Pydantic
- SQLAlchemy
- Alembic
- PostgreSQL
- pgvector
- Redis optional
- Temporal or equivalent durable orchestrator

## Agent layer

- Provider-neutral internal agent abstraction
- Structured outputs
- Tool schemas
- MCP-compatible tools where useful

## Repository analysis

- tree-sitter
- language-specific parsers
- ripgrep
- git
- static dependency analysis
- optional language-server integrations

## Execution

- Docker
- isolated filesystem
- CPU / memory limits
- network policy
- secrets injection
- ephemeral credentials

## Frontend

Optional initially.

Later:

- React / Next.js
- workflow timeline
- ticket dashboard
- agent trace
- PR evidence view
- cost dashboard
- evaluation dashboard

## Observability

- OpenTelemetry
- structured logging
- metrics
- trace IDs
- agent/tool events
- workflow timelines

---

# 19. Security Model

This project must have serious security controls.

## Secrets

Agents never receive raw long-lived secrets in prompt context.

Use:

- scoped environment injection
- short-lived tokens
- secret manager
- repository-specific GitHub App credentials

## Network access

Default-deny.

Allow-list necessary external services.

## Command execution

- isolated containers
- resource limits
- command audit
- no host filesystem access
- no privileged Docker socket
- no unrestricted production credentials

## Repository permissions

Use least privilege.

An agent assigned to repo A should not access repo B unless explicitly authorized.

## Prompt injection

Treat repository content as untrusted.

Examples:

- malicious README instructions
- source comments telling the model to leak secrets
- test fixtures containing prompt-like content

Repository content should never be allowed to override system policy.

---

# 20. Policy Engine

Create explicit policies instead of hiding safety logic inside prompts.

Examples:

```yaml
rules:
  - name: block_sensitive_auth_changes
    when:
      risk_tags: ["authentication", "authorization"]
    require:
      - human_plan_approval
      - security_review
      - human_merge_approval

  - name: destructive_migration
    when:
      migration_type: "destructive"
    action: BLOCK
```

Policy decisions should be persisted and auditable.

---

# 21. Cost Controls

Track cost per ticket.

Metrics:

- input tokens
- output tokens
- model calls
- execution minutes
- sandbox cost
- retry cost
- total ticket cost

Budgets:

```yaml
ticket_budget:
  max_model_cost_usd: 20
  max_execution_minutes: 45
  max_builder_iterations: 5
  max_review_loops: 3
```

Agents should stop and escalate if a budget is exceeded.

---

# 22. Observability

Every agent action should emit an event.

Example:

```json
{
  "event_type": "agent_tool_call",
  "workflow_id": "...",
  "ticket_id": "ENG-142",
  "agent": "builder",
  "tool": "run_tests",
  "timestamp": "...",
  "duration_ms": 12401,
  "result": "success",
  "cost_usd": 0.18
}
```

Dashboards:

- tickets by state
- completion rate
- first-pass acceptance
- regression rate
- average cycle time
- average model cost
- failures by reason
- human intervention rate
- agent performance by model
- review disagreement rate

---

# 23. Evaluation System

This is mandatory for the portfolio project.

Do not evaluate only with synthetic toy tickets.

## 23.1 Historical-ticket benchmark

Select 30 to 50 historical tickets from mature open-source projects.

For each:

1. Identify issue / ticket.
2. Identify repository state immediately before accepted human PR.
3. Hide accepted PR from the worker agents.
4. Give the system the issue and pre-change repository.
5. Let it independently implement.
6. Run the repository's tests.
7. Evaluate acceptance criteria.
8. Compare to the accepted human implementation.

Metrics:

- task completion
- tests passing
- hidden tests passing
- functional equivalence
- regression rate
- changed-file overlap
- implementation complexity
- review findings
- human review time
- cost
- cycle time

## 23.2 Human review

A human should review agent PRs blind where possible.

Rating dimensions:

- correctness
- maintainability
- security
- architectural fit
- unnecessary complexity
- ticket satisfaction
- review burden

## 23.3 Ablations

Compare:

- single agent vs multi-agent
- builder self-review vs independent review
- no impact graph vs impact graph
- no repository retrieval vs repository retrieval
- cheap model vs frontier model
- generated tests vs existing tests only

This turns the project into an engineering research artifact.

---

# 24. Core Metrics

Primary:

- Ticket Acceptance Rate
- First-Pass Acceptance Rate
- Regression Rate
- Escaped Defect Rate
- Human Review Minutes
- Median Cycle Time
- Cost Per Accepted Ticket
- Human Override Rate

Secondary:

- Clarification Rate
- False Clarification Rate
- Average Builder Iterations
- Review Disagreement Rate
- Generated-Test Utility
- Security Finding Rate
- Rollback Rate

---

# 25. Demo Scenarios

Build polished demos.

## Demo 1: straightforward feature

Linear ticket:

"Add customer-status filtering to customer list."

Expected:

- plan
- code
- tests
- PR
- independent review
- acceptance evidence

## Demo 2: ambiguous requirement

Ticket:

"Automatically reprice customers."

Expected:

The system refuses implementation and requests clarification concerning:

- eligible customers
- contract restrictions
- rounding
- notification
- rollback
- authorization

## Demo 3: regression-sensitive change

Ticket modifies shared pricing logic.

Expected:

Impact graph identifies:

- quotes
- invoices
- renewal forecasts
- reporting

System runs additional tests.

## Demo 4: data-engineering ticket

"Incrementally ingest updated customer records every 24 hours."

Expected:

- source analysis
- watermark strategy
- idempotency
- schema evolution
- pipeline implementation
- data-quality tests
- replay test

## Demo 5: AI-engineering ticket

"Add grounded answers with citations to support assistant."

Expected:

- retrieval changes
- citation schema
- eval cases
- hallucination tests
- latency benchmark
- PR

---

# 26. Integration With PE Portfolio Value Creation OS

Keep this optional but architect for it.

The Value Creation OS determines:

**What should the company improve?**

Agentic Delivery OS determines:

**How can approved technical work be executed safely?**

Example:

```text
Portfolio Value Creation OS
    |
    | Initiative:
    | "Automate Tier-1 support triage"
    |
    v
Approved Technical Workstream
    |
    v
Agentic Delivery OS
    |
    +-> requirements
    +-> architecture
    +-> tickets
    +-> implementation
    +-> PR review
    +-> deployment
    |
    v
KPI measurement
    |
    v
Value Creation OS
    |
    v
Realized savings / EBITDA tracking
```

This creates a full loop:

```text
Investment Thesis
    ->
Operating Opportunity
    ->
Technical Work
    ->
Software Delivery
    ->
KPI Improvement
    ->
Financial Realization
```

Do not tightly couple the repositories. Use APIs / events.

---

# 27. Data Model

Core tables:

## work_items

- id
- external_id
- source
- title
- description
- repository_id
- risk_tier
- worker_profile
- state
- created_at
- updated_at

## acceptance_criteria

- id
- work_item_id
- description
- verification_type
- status

## workflows

- id
- work_item_id
- orchestrator_workflow_id
- state
- started_at
- completed_at

## agent_runs

- id
- workflow_id
- agent_type
- model_provider
- model_name
- started_at
- completed_at
- tokens_in
- tokens_out
- cost
- result

## tool_calls

- id
- agent_run_id
- tool_name
- input_hash
- result
- duration
- artifact_ref

## repository_snapshots

- id
- repository_id
- commit_sha
- indexed_at

## code_symbols

- id
- snapshot_id
- path
- symbol
- type

## dependency_edges

- source_symbol_id
- target_symbol_id
- relationship

## pull_requests

- id
- work_item_id
- external_pr_id
- branch
- url
- status

## review_findings

- id
- pull_request_id
- reviewer_type
- severity
- category
- description
- evidence
- status

## verification_evidence

- id
- criterion_id
- type
- source
- result
- artifact_ref

## policy_decisions

- id
- workflow_id
- policy
- decision
- reason

## audit_events

- id
- workflow_id
- actor
- event_type
- payload
- timestamp

---

# 28. API Surface

Initial API:

```text
POST   /webhooks/linear
POST   /webhooks/github

GET    /work-items
GET    /work-items/{id}
POST   /work-items/{id}/clarifications
POST   /work-items/{id}/approve-plan
POST   /work-items/{id}/cancel

GET    /workflows/{id}
GET    /workflows/{id}/events

GET    /pull-requests/{id}/evidence
POST   /pull-requests/{id}/human-review

GET    /evaluations
POST   /evaluations/run
GET    /metrics
```

---

# 29. Proposed Repository Structure

```text
agentic-delivery-os/
|
|-- README.md
|-- LICENSE
|-- pyproject.toml
|-- docker-compose.yml
|-- .env.example
|-- Makefile
|
|-- docs/
|   |-- architecture.md
|   |-- product-spec.md
|   |-- security-model.md
|   |-- evaluation-methodology.md
|   |-- demo-guide.md
|   |-- contributing.md
|   |
|   `-- adr/
|       |-- ADR-001-durable-orchestration.md
|       |-- ADR-002-agent-separation-of-duties.md
|       |-- ADR-003-repository-context.md
|       |-- ADR-004-sandbox-model.md
|       `-- ADR-005-policy-engine.md
|
|-- src/
|   `-- agentic_delivery/
|       |-- api/
|       |-- domain/
|       |-- orchestration/
|       |-- agents/
|       |   |-- intake/
|       |   |-- requirements/
|       |   |-- planner/
|       |   |-- builder/
|       |   |-- tester/
|       |   |-- reviewer/
|       |   |-- regression/
|       |   |-- security/
|       |   `-- acceptance/
|       |
|       |-- integrations/
|       |   |-- linear/
|       |   |-- jira/
|       |   |-- github/
|       |   `-- models/
|       |
|       |-- repository/
|       |   |-- indexer/
|       |   |-- symbols/
|       |   |-- dependency_graph/
|       |   `-- retrieval/
|       |
|       |-- execution/
|       |   |-- sandbox/
|       |   |-- commands/
|       |   `-- artifacts/
|       |
|       |-- policy/
|       |-- evaluation/
|       |-- observability/
|       |-- storage/
|       `-- config/
|
|-- tests/
|   |-- unit/
|   |-- integration/
|   |-- e2e/
|   |-- security/
|   `-- fixtures/
|
|-- evals/
|   |-- benchmark/
|   |-- historical_tickets/
|   |-- scorers/
|   `-- reports/
|
|-- demos/
|   |-- sample_repo/
|   |-- sample_tickets/
|   `-- recordings/
|
|-- scripts/
|   |-- bootstrap.sh
|   |-- index_repo.py
|   |-- run_local_ticket.py
|   `-- run_eval.py
|
`-- infra/
    |-- docker/
    |-- temporal/
    `-- terraform/
```

---

# 30. Configuration Model

Example:

```yaml
system:
  environment: development

integrations:
  issue_tracker:
    provider: linear

  source_control:
    provider: github

orchestration:
  provider: temporal

execution:
  provider: docker
  network_policy: restricted
  max_runtime_minutes: 45

agents:
  planner:
    model_profile: reasoning_high
  builder:
    model_profile: coding_high
  reviewer:
    model_profile: reasoning_high
    independent_context: true
  acceptance:
    model_profile: reasoning_high

policy:
  default_merge_requires_human: true
```

---

# 31. MVP Definition

The MVP should be narrow but real.

## MVP success criteria

A Linear ticket can be assigned to the system.

The platform can:

1. Receive the ticket.
2. Clone a configured GitHub repository.
3. Analyze ticket requirements.
4. Ask for clarification if needed.
5. Generate a plan.
6. Create an isolated branch.
7. Modify code.
8. Add tests.
9. Run tests / lint.
10. Push branch.
11. Open PR.
12. Run independent reviewer.
13. Map acceptance criteria to evidence.
14. Post results to PR and Linear.
15. Require human merge.

Supported initially:

- Python repositories
- GitHub
- Linear
- Docker sandbox
- one model provider adapter
- software-engineering tickets

Do not add Jira, JavaScript, Kubernetes, or multiple providers until this path is excellent.

---

# 32. Milestone Roadmap

## Milestone 0: Architecture

Deliverables:

- product spec
- architecture
- domain model
- state machine
- risk policy
- ADRs
- sample tickets

Exit criteria:

Architecture review complete.

## Milestone 1: Ticket -> Plan

Deliverables:

- Linear webhook
- ticket normalization
- requirements agent
- risk classifier
- planner
- persisted workflow

Exit:

A real Linear ticket produces a structured implementation plan.

## Milestone 2: Plan -> Local Change

Deliverables:

- GitHub adapter
- repo clone
- Docker sandbox
- builder
- branch
- commits
- targeted test execution

Exit:

Agent completes a controlled Python ticket locally.

## Milestone 3: Pull Request

Deliverables:

- push
- PR creation
- PR evidence template
- CI status ingestion

Exit:

System opens a useful PR with evidence.

## Milestone 4: Independent Review

Deliverables:

- reviewer
- acceptance agent
- test agent
- correction loop

Exit:

Reviewer can reject builder output and trigger revision.

## Milestone 5: Regression Intelligence

Deliverables:

- repository index
- symbol relationships
- impact graph
- targeted regression tests

Exit:

Changed symbols automatically expand the validation scope.

## Milestone 6: Security and Policy

Deliverables:

- risk tiers
- policy engine
- secret scanning
- dependency scanning
- human approval gates

Exit:

High-risk ticket is blocked or escalated correctly.

## Milestone 7: Evaluation Harness

Deliverables:

- historical ticket dataset
- pre-PR repo snapshots
- scorers
- cost metrics
- benchmark report

Exit:

At least 30 real historical tickets evaluated.

## Milestone 8: Data / AI Workers

Deliverables:

- data engineer profile
- AI engineer profile
- data scientist profile

Exit:

End-to-end demos across multiple work types.

## Milestone 9: Jira + Additional Language

Add only after core system is stable.

## Milestone 10: Value Creation OS Integration

Deliverables:

- initiative -> workstream API
- KPI callback
- realization event

Exit:

Approved PE initiative creates governed technical work and returns execution status.

---

# 33. Initial GitHub Issues

Create these issues in the new repository.

## Foundation

1. Define domain models and enums.
2. Implement workflow state machine.
3. Add PostgreSQL persistence.
4. Add structured audit events.
5. Add configuration loading.
6. Add local Docker development environment.

## Linear

7. Build Linear webhook endpoint.
8. Add Linear ticket adapter.
9. Normalize Linear ticket to WorkItem.
10. Add ticket status updates and comments.

## GitHub

11. Build GitHub App authentication.
12. Add repository clone / checkout.
13. Add branch creation.
14. Add commit / push.
15. Add PR creation.
16. Add PR comment adapter.

## Agent core

17. Define Agent interface.
18. Define tool registry.
19. Build structured-response enforcement.
20. Add model-provider adapter.
21. Add agent run persistence.
22. Add token / cost tracking.

## Requirements

23. Build Requirements Agent.
24. Add acceptance criteria extraction.
25. Add ambiguity detection.
26. Add clarification workflow.

## Planning

27. Build Planner Agent.
28. Add repository context retrieval.
29. Add implementation plan schema.

## Execution

30. Build Docker sandbox.
31. Add command execution controls.
32. Add filesystem controls.
33. Add timeout / resource limits.
34. Add artifact collection.

## Builder

35. Build Builder Agent.
36. Add edit / patch tools.
37. Add test execution.
38. Add commit generation.

## Review

39. Build Reviewer Agent.
40. Build Acceptance Agent.
41. Build Test Agent.
42. Add review -> builder correction loop.

## Regression

43. Build Python symbol indexer.
44. Build import graph.
45. Build call dependency extraction.
46. Map tests to modules.
47. Build impact traversal.
48. Generate regression plan.

## Policy

49. Define risk tiers.
50. Implement Policy Engine.
51. Add approval gates.
52. Add sensitive-change detectors.

## Security

53. Add secret scanner.
54. Add dependency vulnerability checks.
55. Add prompt-injection defense tests.
56. Add sandbox security tests.

## Observability

57. Add OpenTelemetry traces.
58. Add workflow metrics.
59. Add per-ticket cost accounting.
60. Add agent event timeline.

## Evaluation

61. Define historical benchmark format.
62. Build repo snapshot loader.
63. Build ticket benchmark runner.
64. Add correctness scorer.
65. Add regression scorer.
66. Add human-review rubric.
67. Add benchmark report generator.

---

# 34. Definition of Done for a Ticket

A ticket is DONE only when:

- acceptance criteria are explicit
- implementation exists
- required tests pass
- new behavior is tested
- independent reviewer approves
- regression review passes
- security policy passes
- evidence package exists
- required human approvals exist
- PR merges
- deployment validation passes when applicable
- issue tracker is updated
- audit trail is complete

---

# 35. Definition of Done for the Portfolio Project

The project should not be considered portfolio-complete merely because the demo works.

Strong completion means:

1. At least one real issue tracker integration.
2. Real GitHub pull requests.
3. Real isolated execution.
4. Independent review.
5. Ticket-to-test evidence.
6. Impact / regression analysis.
7. Risk policies.
8. Human approval gates.
9. Observability.
10. Cost tracking.
11. 30+ historical real-world ticket evaluations.
12. Published benchmark results.
13. Architecture documentation.
14. Security model.
15. Recorded demo.
16. At least three worker profiles.
17. Clear limitations documented.
18. Reproducible local setup.
19. CI for the platform itself.
20. One optional PE Value Creation OS integration demo.

---

# 36. README Positioning

Suggested opening:

> Agentic Delivery OS is a governed multi-agent software delivery platform that converts tickets into tested, independently reviewed pull requests. It coordinates specialized planning, implementation, testing, regression, security, and acceptance agents while preserving human control over sensitive decisions and merges.

Then immediately show:

```text
Linear / Jira
   ->
Requirements
   ->
Risk
   ->
Plan
   ->
Build
   ->
Test
   ->
PR
   ->
Independent Review
   ->
Regression Analysis
   ->
Human Approval
```

Avoid marketing claims about replacing engineering teams.

Position it as:

**Agent-assisted technical execution with governance and evidence.**

---

# 37. Resume Positioning

Once mature:

**Agentic Delivery OS — Independent AI Engineering Project**
*Python, FastAPI, PostgreSQL, Temporal, Docker, GitHub, Linear, LLM APIs*

- Built a governed multi-agent engineering platform that converts issue-tracker tickets into isolated code changes, tested pull requests, and auditable acceptance evidence across software, AI, and data workflows.
- Designed independent planner, builder, reviewer, regression, security, and acceptance agents with risk-based human approval gates and ticket-to-test traceability.
- Developed repository impact analysis linking changed code to downstream callers, APIs, data contracts, and tests to expand regression coverage automatically.
- Evaluated the platform against historical real-world software tickets using pre-change repository states, measuring functional acceptance, regression rate, human review effort, cycle time, and cost per accepted ticket.

Only add numerical results after the benchmark actually exists.

---

# 38. Interview Story

Short:

> "I wanted to go beyond building another coding agent. I built a governed delivery system where an issue can be assigned to an agentic worker, implemented in an isolated environment, turned into a PR, and then independently reviewed against the original ticket. A separate regression agent analyzes what else in the repository could have been affected, and high-risk changes require human approval. The goal is not autonomy for its own sake. The goal is reliable, auditable engineering throughput."

PE version:

> "The broader thesis is that AI value creation eventually has to turn into execution. My Value Creation OS helps determine what a portfolio company should improve. Agentic Delivery OS is designed to execute approved technical work safely, return evidence, and ultimately connect deployment back to operating KPIs and value realization."

---

# 39. Critical Design Principles

1. Evidence over agent confidence.
2. Independent review over self-review.
3. Human authority over sensitive changes.
4. Requirements before implementation.
5. Reproducibility over impressive demos.
6. Real benchmarks over anecdotal examples.
7. Provider neutrality over model lock-in.
8. Durable workflows over synchronous scripts.
9. Explicit policy over prompt-only governance.
10. Narrow permissions over broad agent access.
11. Repository-aware validation over generic testing.
12. Measured business / engineering outcomes over "tickets completed."

---

# 40. Explicit Non-Goals for Early Versions

Do not initially build:

- fully autonomous production deploys
- unrestricted shell agents
- every programming language
- every issue tracker
- custom IDE
- proprietary model training
- microservice sprawl
- custom graph database without demonstrated need
- visual workflow builder
- automatic merge of high-risk changes

Those can distract from the central engineering thesis.

---

# 41. Recommended First Build Sequence

The first repository handoff should begin here:

1. Create repository skeleton.
2. Add product spec and ADRs.
3. Implement WorkItem / AcceptanceCriterion models.
4. Implement state machine.
5. Add PostgreSQL persistence.
6. Add Linear webhook and adapter.
7. Add GitHub App adapter.
8. Add Docker sandbox.
9. Add one provider-neutral Agent interface.
10. Implement Requirements Agent.
11. Implement Planner Agent.
12. Implement Builder Agent.
13. Open a real PR.
14. Implement Reviewer Agent.
15. Implement Acceptance Agent.
16. Add requirement-to-test traceability.
17. Add regression analysis.
18. Add policy gates.
19. Add observability and cost accounting.
20. Start historical-ticket benchmark.

A repository agent receiving this handoff should **not** try to build the complete vision in one pass.

It should build vertically, one reliable ticket lifecycle at a time.

---

# 42. First Vertical Slice Acceptance Test

The first meaningful end-to-end milestone:

Given:

- a configured GitHub Python repository
- a Linear ticket assigned to the Agentic Delivery OS worker
- a low-risk feature with explicit acceptance criteria

When:

- the ticket webhook is received

Then:

1. Ticket is normalized.
2. Requirements are validated.
3. Risk = Tier 1.
4. Plan is generated.
5. Repository is cloned into isolated Docker environment.
6. Branch is created.
7. Builder modifies code.
8. Builder adds tests.
9. Tests pass.
10. Branch is pushed.
11. PR is opened.
12. Reviewer independently reviews.
13. Acceptance Agent maps each criterion to test evidence.
14. Linear changes to "In Review."
15. Human reviewer receives PR.
16. System cannot merge without human approval.
17. Complete audit trail is persisted.

This should be the first demo that works reliably.

---

# 43. Long-Term Research Questions

The project should eventually answer:

- Does independent agent review materially reduce defects?
- Does repository impact analysis reduce regressions?
- What ticket classes are safe for high autonomy?
- At what complexity does agent performance fall sharply?
- When should an agent ask for clarification instead of attempting implementation?
- Which model configuration produces the best cost-adjusted success rate?
- How much human review time is saved?
- Do generated tests detect real defects or merely mirror implementation?
- Can agents detect cross-service and data-contract impacts reliably?
- How should confidence influence autonomy?
- How should organizations allocate work between humans and agentic workers?

These questions make the project substantive beyond the demo.

---

# 44. Final Product Thesis

The valuable product is not:

> "AI writes code."

The valuable product is:

> "A governed agentic workforce can receive real technical work, execute it in isolated environments, prove that requirements were satisfied, independently inspect its own output, detect downstream risk, and deliver an auditable pull request to a human decision-maker."

That is the standard the repository should build toward.
