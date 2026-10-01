# Derived historical qualification inputs

ADR-013 uses explicit schema-2 reference provenance and a protected schema-2 review
input wrapper. Existing schema-1 historical and synthetic records retain their byte
shape. A derived record is never accepted by legacy inspection or synthetic calibration
anchor parsers.

`ReferenceProvenanceV2` binds the task, baseline source, accepted commit, relocated
oracle, production patch, executable reference, complete derivation, provider-reported
issue/PR linkage and explicit derived-data authorization. Current preparation reconstructs
the derivation with trusted disjoint worker scopes, checks all changed original paths
against current repository protection rules, and validates both original and derived
rights attestations against exact current policy pins. The task description must equal
the frozen pre-acceptance issue body (apart from surrounding whitespace); its title is
the neutral `Historical issue #N`. Direct preparation and review resolution enforce
this projection even when no importer is invoked.

`DerivedQualificationInput` contains the existing qualification input inline plus exact
task, provenance and reference-provenance artifact identities. The read-only resolver
reconstructs those bindings and computes the forbidden reference closure. This includes
the full accepted tree, capture/inventory objects, accepted file identities, production
patch, executable reference, derivation and aggregate proofs. The current unverified
issue title and its provider evidence container are excluded from supporting documents
and rubrics. Previously written wrapper/reference/derivation objects cannot bypass the
closure by being supplied as a different supporting aggregate. Authorized source and
oracle files enter reviewer context only through their structured evidence roles.

The resolver proves content integrity, not current execution authority or filesystem
separation. Preparation validates trusted scopes and current policy before effectful
callers invoke it. Current controller and admission callers additionally require all
three wrapper artifact references to equal the exact current preparation request. An
otherwise coherent alternative proof or a stripped inner input does not satisfy this
binding.

Both `runtime-review-input-v1` and `qualification-input-v2` checkpoints retain the outer
wrapper digest, as do review context, review evidence and admission comparisons. The
inner value is returned to consumers only after the protected chain is validated.
Current deterministic and model active guards honor the earlier of the parent and
derived rights expirations; exact policy/configuration/grant digests remain frozen.
Current preparation is repeated at effect boundaries and admission revalidates current
rights. Rights attestations never authorize runtime spending or model calls.

Owned tests exercise read-only reconstruction, exact current-request binding, current
protected paths, disjoint scopes, coherently rehashed task wording, forbidden supporting
documents/rubrics, both checkpoints, controlled full controller/admission/resume paths,
wrapper-stripping denial and cancellation at the shorter rights expiry. Fabricated or
controlled reports and mocked model transports in these tests are protocol evidence
only. They establish no actual historical runtime result or dataset admission.
