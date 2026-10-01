# Canonical campaign attempt allocation

`CampaignAllocator` allocates metadata and finite ledger capacity for one explicitly
authorized schema-3 campaign ordinal. It does not export source, call providers,
run Docker, score a candidate or promote a phase. Its immutable receipt records the
allocation event as `ATTEMPT_ALLOCATED_NOT_EXECUTED`; it is not a live execution-state
claim and parsing that receipt grants no authority.

Current trusted policy and authorization bind the exact campaign, ordinal, phase,
arm, original task/qualification, execution/preparation policy and ledger target.
Qualification is revalidated for campaign use. The frozen complete schedule, parity,
manifest identities and worst-case campaign sum are reconstructed before allocation.
Every arm ceiling must satisfy current policy. A grant lasts at most 24 hours;
actual attempt duration remains bounded by the original frozen arm wall limit.

The only new account is `campaign:<full-campaign-artifact-digest>:<ordinal>`, with
exact frozen arm limits. Its unique ledger key prevents concurrent controllers from
allocating a second budget for the same ordinal. The original account creation time
becomes the attempt start; the deadline is the earlier of that time plus the arm wall
limit and the allocation grant expiry. Retrying never resets this clock or capacity.

The controller stores immutable allocation and existing attempt-binding checkpoints
on that same account. PostgreSQL account-row locking and SQLite immediate transactions
serialize claims. No separate campaign control account or ledger migration is needed.
Concurrent identical calls converge; conflicting grants/checkpoints deny. A crash or
lost acknowledgement between steps can leave partial metadata. Repeating the exact
request completes those steps from the original account timestamp, while the read-only
validator refuses incomplete checkpoints. Unexpected prior usage in a partial allocation
is rejected. An unresolved reservation denies allocation retry and remains charged;
failed attempts are not replaced or removed from the frozen denominator.

The policy/grant ledger pin hashes a normalized connection target. SQLite uses the
resolved path and host-platform case normalization; PostgreSQL uses explicit host,
user and database, defaulting only the port to 5432. Passwords are excluded and URL
queries or implicit/socket hosts are refused. A second database target cannot reuse
the same approval. This identifies trusted configuration, not cryptographic database
contents: same-target replacement, DNS changes, storage administrators and unauthorized
policy retargeting remain outside this local consistency guarantee. Operators must keep
one immutable trusted ledger target for the lifetime of an exact campaign authorization.

`validate()` reconstructs current allocation metadata without writes. It can inspect
an existing allocation with an outstanding reservation, but cannot authorize that
operation's retry. The explicit `scoring_execution()` adapter rechecks allocation
through current providers and binds the existing schema-2 scorer to the exact canonical
account/attempt; the scorer still enforces its own active-operation ownership and
refuses unrelated unknown reservations. The adapter mints neither a spending grant
nor another account. Existing manual v2 scoring and all v1 contracts are unchanged.

No phase promotion is inferred. Future source export must additionally use current
`worker-export` qualification authority; the allocator exposes no worker payload.
The existing completed semantic reader still requires an idle account, as documented
in the scoring consumer. This slice does not enable semantic model calls.

The frozen preparation reservation is a contract ceiling, not proof of reconciled
actual preparation cost. Worst-case attempt allocations plus that reservation must fit
the frozen campaign and current policy caps. A complete actual-cost claim still needs
a separately verified inventory of preparation expenditure and retained uncertainty.

Owned tests use real SQLite accounting and a controlled qualification boundary. They
cover concurrent allocation, partial-write recovery, expiry/revocation, wrong bindings,
duplicate ledger targets, retained unknown usage and the existing scorer adapter with
controlled Docker results. A separately provisioned disposable PostgreSQL database
exercises six simultaneous controllers; its fixture never creates, deletes or truncates
a shared database. These checks establish neither a qualified corpus nor campaign results.
