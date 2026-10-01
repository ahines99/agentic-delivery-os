# 2026-10-01: Linear pickup contract v1 (DO-1, DO-2)

## What changed

- **Opt-in label.** The Linear monitor requires the `delivery-ready` label, which is
  configurable per repository through `linear_pickup_label`.
- **Repository line.** The `Repository:` line is now mandatory. It may name the configured id,
  the GitHub name, or an alias listed in `linear_repository_names`.
- **Digest.** Both settings are excluded from the execution digest.
- **Docs.** [ADR-036](../adr/ADR-036-linear-pickup-contract.md), the runbook, the README and the
  automatic-delivery guide describe the new ticket requirements.

## Stopgap applied to the installed service

Before this change was built, `automatic_execution` was set to `false` for
`ahines99/agentic-delivery-os` in the ignored `config.local.json`. The previous file is kept at
`.local/config.local.json.bak-2026-10-01`. No workflow was active: the newest runs were PER-16
and PER-17, both already `POLICY_BLOCKED`. The monitor reloads settings on every poll, so no
restart was needed. Re-enable automatic execution after this change is installed.

## Verification

- `tests/test_linear_monitor.py`: 82 passed. The new tests cover:
  - the PER-16 replay, which shows no claim;
  - six tickets outside the contract that are never assigned;
  - an aliased name with a custom label;
  - a disabled label that still requires the repository line;
  - routing settings leaving the execution digest unchanged.
- The live configuration produces the identical execution digest
  (`22e8f686…c1c3`) under the old and new code.

## Not verified

Not installed in the local service, and not exercised against live Linear tickets.
