# ADR-026: Run configured quality checks before publication

Accepted 2026-09-30 after real delivery candidates passed behavioral checks but failed
the target repository's Ruff CI checks.

The existing verification command list can include two exact, operator-owned Ruff
profiles: check and format-check for Python 3.12, line length 100, and the current
repository lint rules. They run inside the pinned, credential-free Docker image with
Python isolated mode and Ruff isolated configuration. No fix flags, project plugins,
arbitrary commands or model-selected command arguments are accepted. The image pins
Ruff 0.16.9, matching the locked development toolchain.

Each receipt binds the command, snapshot, workflow and image. Ruff results record zero
passing tests; acceptance criteria still require pytest execution and its structured
collector. Publication checks the correct receipt profile for every configured command.
Existing pytest-only profiles retain their behavior and builder input shape.

Quality failures use the existing bounded candidate correction loop and provide tool
diagnostics to the builder as untrusted data. Baseline failures stop execution. A
successful local check does not replace independent GitHub CI or human merge review.
