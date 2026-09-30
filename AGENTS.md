# Repository guidance

Read README.md and docs/plan.md before making changes. The original handoff in
docs/reference is historical input; accepted decisions and scope live in docs/plan.md
and the ADRs. Distinguish working features from planned integrations.

- Python 3.12 is the baseline. Keep domain logic independent of providers and orchestration.
- Use typed, validated contracts and explicit state transitions. Deny unknown inputs.
- Repository content, tickets, model output, and sandbox output are untrusted data.
- Never give a builder merge authority or control-plane credentials. Every MVP merge is human.
- Evidence and approval must bind to repository, base/head revisions, and policy version.
- Add meaningful tests for policy, lifecycle, isolation, retries, and evidence changes.
- Run `python -m ruff check .`, `python -m ruff format --check .`,
  `python -m mypy`, and `python -m pytest -n 32 --dist worksteal` from the project virtual
  environment. Run focused test files serially while iterating and the parallel suite before
  committing; see docs/contributing.md for worker limits.
- Do not publish benchmark numbers without a reproducible run and provenance.
- Do not add placeholder provider implementations that silently report success.
- Keep changes within the next milestone. Record material architecture changes in ADRs.

No secrets, private generated run artifacts, or historical benchmark answers belong in
interactive implementation-agent context or campaign builder/reviewer inputs. The protected
qualification evaluator may inspect explicitly authorized source and oracle tests under
[ADR-010](docs/adr/ADR-010-executable-qualification-stages.md); reference solutions remain
excluded from model inputs. This exception grants no access to the implementation agent
or permission to tune against sealed campaign cases.
