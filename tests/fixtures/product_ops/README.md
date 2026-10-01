# Synthetic Product Ops contract fixtures

These public-format payloads derive from authored Product Ops fixtures and its mock publisher.
The documentation fixture is a synthetic one-file request. No real credentials, human approvals,
Linear mutations or private repository snapshots are present. Tests sign with ephemeral keys,
set a simulated live transport marker and use read-only mock GraphQL responses. That marker
exercises live-format validation; it does not make these live publication evidence.

Production admission rejects mock-transport envelopes. The tests separately verify that default.
