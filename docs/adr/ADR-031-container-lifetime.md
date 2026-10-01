# ADR-031: Container lifetime independent of its worker

Status: implemented and installed in the controlled local runtime; complete release qualification remains open.

## Problem

The host enforces the approved command timeout and removes the container in a
`finally` block. If that worker dies, neither action can complete. ADR-015 adds
workflow recovery cleanup, but that also needs a surviving worker and Docker access.
The former fixed two-hour container keepalive outlasted short approved commands.

## Decision

The fixed container command is an isolated Python namespace-init process that exits
after the approved command timeout plus 60 seconds. The allowance covers the bounded
snapshot-transfer and report-read operations. It starts with the container, cannot be
renewed through a candidate file or model output, and has an explicit `no` restart
policy. Command timeouts must be actual integers from 1 through 1800 seconds.

The host still enforces the original command timeout without the allowance. Normal
cleanup and ADR-015 recovery cleanup remain responsible for removing the container.
The independent lifetime bounds a running orphan while the Linux daemon is healthy;
it does not report delivery success or turn an uncertain cleanup into verified removal.

## Verification and limits

The owned Docker test starts a long-running candidate, kills its Python worker and
Docker client process tree, and observes the container exit without a replacement
worker, host timeout, stop, or removal command. The candidate also attempts to suspend
namespace PID 1 with SIGSTOP. Test-parent removal happens only after the observation
and is explicitly hygiene, not product cleanup evidence. Unit checks cover strict
timeout validation, the command budget and unchanged host timeout/normal cleanup.

The lifetime includes a fixed allowance; it is not an exact command deadline after
worker loss. Setup delays can shorten the usable command window. It does not remove
stopped container metadata, fence a partitioned worker from later creating another
container, or guarantee timing while the host/VM/daemon is suspended or unavailable.
Durable run fencing remains separate work. The existing single-tenant runtime scope
and human merge requirements remain unchanged.

## Recorded local check

On 2026-09-30 the ten timeout/profile cases and actual worker-tree termination case
passed together: **11 passed in 75.17 seconds** on Windows with Docker Desktop,
using image `sha256:5edf3f631f069f4ce7e1e4eb0fb13ea2562cccb240aea91627889e574e2de224`.
The container exited with status 0 and no OOM/restart after the owned worker tree
was killed. No parent removal occurred before that observation. The independent
execution/cleanup/timeout unit selection passed **44 tests**. Ruff, formatting and
mypy passed. [Hosted CI](https://github.com/ahines99/agentic-delivery-os/actions/runs/36737373590)
subsequently passed all jobs at `430bc19`: 3,304 tests per Python version and 130
service integration tests. Application-identical source was [installed at `f3bcbc6`](../local-runtime-upgrade.md).
The long Windows feature run and complete MVP qualification remain separate.
