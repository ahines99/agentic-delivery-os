# ADR-003: Offline Docker prototype with brokered external access

- Status: Accepted for the implementation plan
- Date: 2026-09-27

## Context

Target repository tests, imports, dependency installation, Git hooks, and generated programs can execute arbitrary code. Command allowlists cannot make that code trustworthy. The blueprint's Docker sandbox and restricted network configuration require runtime-specific enforcement before any execution milestone.

## Decision

Use ephemeral Linux containers for the local single-tenant, operator-approved repository prototype. This is not an isolation claim for mutually hostile tenants or arbitrary public code. Containers share a kernel; rootless execution reduces privilege but does not replace a stronger host isolation boundary. A dedicated disposable execution VM is recommended for connected development and required before broadening the repository trust model. Never expose a general Docker API to models.

The execution service admits a fixed profile with:

- Image pinned by digest; dependency set recorded and scanned; non-root UID/GID.
- Read-only root filesystem, bounded temporary writable mounts, and only a dedicated per-run workspace/artifact volume.
- All Linux capabilities dropped, `no-new-privileges`, default seccomp or stricter tested profile, and host MAC policy where supported.
- No privileged mode, devices, host PID/IPC/network namespaces, host home/workspace mounts, Docker/container runtime socket, SSH agent, cloud identity, or control-plane secrets.
- Explicit CPU, memory, process, elapsed-time, disk/workspace, and output limits enforced by the runtime plus external watchdog. Docker memory limits alone do not bound writable storage.
- `--network none` for build/test execution. No inherited control-plane network, published port, proxy environment, or credential helper.
- Per-run resource ownership labels; cancellation and timeout terminate the entire process tree; a sweeper removes abandoned resources after crash recovery.

Runtime preflight must prove the controls work on the actual host. Docker Desktop's Linux VM and Windows/WSL paths differ from native Linux; unsupported limits or unsafe mounts make preflight fail rather than silently weakening the profile. Rootless cgroup support and filesystem quota support must be checked. If disk quotas cannot be enforced, use a bounded execution disk/VM and a watchdog before enabling repository execution.

## Network and dependency reality

`network_policy: restricted` in application YAML is only intent. Docker's `none` network supplies loopback only, so repository cloning, package downloads, model calls, and GitHub publication cannot occur in the build container. [Docker none network documentation](https://docs.docker.com/engine/network/drivers/none/) (accessed 2026-09-27).

The trusted fetch broker supplies a fixed repository snapshot. A separate dependency preparation stage resolves locked dependencies into a cached/pinned image or wheelhouse; any package build script executes in a credential-free quarantined environment with the same resource controls. Installation/build hooks never run in the credentialed broker. Offline jobs fail explicitly when dependencies are missing. MVP sample repositories use prebuilt known dependencies.

Later restricted egress requires a real external enforcement mechanism: an authenticated policy proxy/firewall, DNS and redirect validation, IPv4/IPv6 controls, metadata/private-address blocks, and tests showing no bypass. An internal Docker network, HTTP proxy environment variable, or hostname allowlist alone is insufficient evidence. Such networking is not part of the initial offline profile.

The model adapter and tool dispatcher live in the control plane. The sandbox does not require network access to call an LLM. Publication happens in a separate broker after artifact validation; no GitHub or Linear credentials enter execution.

## Alternatives and consequences

Running an unrestricted local shell would simplify setup but expose the developer machine and secrets. Broad network access would simplify package installation but undermine the default-deny claim. A remote microVM/runtime service can provide a stronger boundary but adds operational cost and must be evaluated separately rather than implied by the Docker adapter abstraction.

Ordinary Compose services run databases and orchestration for development; they do not constitute the sandbox. Local infrastructure must not mount a Docker socket into a publicly reachable API container. A narrowly scoped execution daemon should be operator-managed and inaccessible from target containers.

Docker's daemon/host-mount risks and rootless behavior are described in [Engine security](https://docs.docker.com/engine/security/) and [rootless mode](https://docs.docker.com/engine/security/rootless/) (accessed 2026-09-27). The required profile and scope restrictions above are project decisions.

## Verification

Before enabling the adapter: test host-path and socket access, DNS/TCP/IPv6/metadata egress, privilege escalation attempts, symlink/artifact traversal, malicious dependency scripts, fork/output/disk exhaustion, cancellation, crash cleanup, and absence of secrets. Publish a runtime-specific report. Failure disables execution; a passing configuration-schema unit test cannot stand in for a host-level isolation test.
