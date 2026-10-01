# Candidate wall-time and sandbox network qualification

The 2026-09-30 acceptance audit identified two concrete missing checks in the
existing P-08/P-09 runtime evidence. These additions exercise existing application
controls; they do not change the execution profile or expand its permissions.

## Candidate wall-time expiry

`tests/test_active_cancellation.py::test_wall_budget_stops_actual_docker_activity_and_records_cleanup_without_cancel`
uses real PostgreSQL, Temporal and Docker with an owned long-running workload.
The candidate activity receives a 20-second wall budget while the Docker command
has a 180-second limit. No cancellation command or approval-expiry injection occurs.

The test observes the running container and child process before waiting for the
production activity's timeout. It requires a single candidate schedule, an actual
`TimeoutError` failure in Temporal history, persisted `FAILED`, a `CLEANED` receipt
with verified absence, no remaining workflow-owned containers and no publication
schedule. History replay also passes. The paid candidate pipeline is replaced by
the owned workload; no real model or provider request occurs.

All four cancellation/cleanup/approval/wall-budget cases passed in **69.84 seconds**
using a disposable PostgreSQL database. The live delivery database was not used.
The new case establishes the configured candidate wall budget, not end-to-end
ticket latency or cancellation of a remote model provider's generation.

## DNS, IPv6 and raw sockets

`tests/test_sandbox_adversarial.py::test_actual_dns_ipv6_and_raw_socket_transports_are_denied`
runs a bounded probe through the production Docker runner. It requires:

- Only the loopback interface in the container namespace.
- A local `ENETUNREACH` rejection when sending a UDP DNS query to an external
  resolver. The query contains only `example.com`, never repository or host data;
  an unanswered request or timeout does not satisfy the assertion.
- IPv6 connection failure due to unavailable routing/address-family/address.
- Permission denial for both raw IP and packet sockets.

The existing fixture checks removal of every exact container created by the test
before fallback cleanup. All six sandbox tests passed in **11.64 seconds**, including
the existing tmpfs, PID, memory and malicious dependency-hook probes.

Both selections used image
`sha256:5edf3f631f069f4ce7e1e4eb0fb13ea2562cccb240aea91627889e574e2de224`.
Ruff, formatting and mypy passed. These test additions left application source
identical to `4ae54e6`. They are now included in the passing 163-test service job
in [complete hosted CI at `63f25f2`](https://github.com/ahines99/agentic-delivery-os/actions/runs/36765230833).
The selected single-host controls
do not establish resistance to arbitrary kernel escape, daemon/host loss or a
compromised host administrator.
