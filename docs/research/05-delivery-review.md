# Review 05 — Delivery engineering and repository readiness

Reviewed 2026-09-27 against the original handoff, working scaffold, product/security specifications and upstream documentation. This review owns delivery sequencing, reproducibility and contribution ergonomics; the accepted decisions live in the plan and ADRs.

## Findings and recommendations

The handoff combines an implementation platform, several worker profiles, integration breadth and a substantial benchmark. The dependency chain is the principal delivery risk: independent review cannot mean much before candidate provenance, isolated execution, authenticated intake and durable retries work. Finish one low-risk Python path first. Gate later breadth on measured outcomes. The [backlog](../backlog.md) makes prerequisites and failure-case acceptance explicit.

The scaffold is suitable for offline contracts and policy demonstrations. Its pure transition graph cannot enforce runtime authorization, and its supplied review/artifact IDs cannot prove independence or authenticity. Keep those limitations beside the demo and README. Add provenance/authentication at the durable boundary rather than presenting a local predicate as an execution gate. Current CLI exit success means a valid fixture was evaluated, including when policy blocks the ticket.

Source review also identified that the initial `RiskTier` field used Pydantic's default coercion, potentially admitting booleans, numeric strings or integral floats as risk labels. The foundation was updated during this review with explicit risk validation and rejection tests. The sensitive-tag allow/deny vocabulary was broadened; it remains a fixture predicate, not independent code-risk classification. The ambiguous sample also carries sensitive/high-risk metadata: its display state requests clarification while `policy.allowed` stays false and records the risk denials. Resolving ambiguity alone therefore cannot authorize that task.

Use a committed `uv.lock` and `uv sync --locked --extra dev`: uv checks lock consistency, and the optional `dev` extra matches this repository's manifest. Run checks from that synchronized environment with `--no-sync` so subsequent commands do not silently modify it. This follows [uv's synchronization semantics](https://docs.astral.sh/uv/concepts/projects/sync/) and its [GitHub Actions integration guide](https://docs.astral.sh/uv/guides/integration/github/).

CI should run on ordinary pull requests and trusted branch pushes with read-only repository permissions and no provider credentials. Keep untrusted candidate execution out of privileged event workflows. GitHub documents both the risks of privileged triggers with untrusted checkout and immutable SHA pinning in its [secure-use guidance](https://docs.github.com/en/actions/reference/security/secure-use). The supplied CI disables persisted checkout credentials and caching, pins tool/action versions, and limits runtime. This reduces unnecessary authority; it is not the product's sandbox boundary.

## Pin provenance and remaining verification

The following pins were resolved directly from their upstream repositories using `git ls-remote` on 2026-09-27:

| Action | Release | Verified commit |
| --- | --- | --- |
| [actions/checkout](https://github.com/actions/checkout/tree/v4.2.2) | v4.2.2 | `11bd71901bbe5b1630ceea73d27597364c9af683` |
| [astral-sh/setup-uv](https://github.com/astral-sh/setup-uv/tree/v6.8.0) | v6.8.0 | `d0cc045d04ccac9d8b7881df0226f9e82c39688e` |

These are selected verified releases, not a claim that they are the newest. CI selects uv 0.12.18, available through the workstation's global Python; the setup also used a project-local uv 0.12.19. The 0.12.18 upstream tag was independently resolved to `01cb90c1a4f88af09906cb60de9766d2add4a062`. Python 3.12 is the project baseline and 3.13 is an additional CI matrix target. Hosted CI has not run during local setup; no remote repository or branch protection is configured. Review and update action pins as maintenance work.

The Windows workstation initially did not resolve `uv` on PATH, while `python -m uv` was available. The development guide links supported global installation options and gives direct `.venv` Python alternatives for checks; it does not require changing PowerShell execution policy. Docker and credentials are unnecessary for the current demo. Docker or a stronger execution substrate becomes a verified prerequisite at M2.

## Decisions to preserve

- No remote issues/PRs/settings are created by this setup; local templates/backlog are ready for later onboarding.
- CI passes establish tested foundation behavior, not live integrations, isolation or benchmark efficacy.
- Real provider adapters fail explicitly on unavailable behavior; avoid success-shaped placeholders.
- Historical evaluation answers, secrets and generated run artifacts stay out of agent context and source control.
- Every MVP merge remains human; later deployment and broader worker profiles require their own decisions.

The practical portfolio claim should be demonstrated behavior with reproducible evidence and visible limits. The original ambition is retained as future options rather than used as a completion checklist for the first release.
