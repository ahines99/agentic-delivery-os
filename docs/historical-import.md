# Offline protected historical import

`evaluation/historical_import.py` validates an already acquired evaluator-only historical bundle
and freezes import/preparation metadata. It is the initial offline importer, not an end-to-end
acquisition service. It makes no network request, executes no repository code or model, creates
no rights or spending grant, and does not admit a task.

`HistoricalImportRequest` contains the existing `PreparationRequest` and an acquisition-evidence
artifact reference. The preparation references retain the existing `HistoricalTask`, `Provenance`
and `ReferenceProvenance` contracts unchanged. Tasks must be pending `independent-agents-v2`
historical drafts; synthetic and legacy records cannot enter this path.

`HistoricalAcquisitionEvidence` binds the exact repository/base, source task and dataset revision,
task/specification digests, issue URL, pre-solution requirements text, accepted commit and URL,
source/oracle/reference/patch references and acquisition timestamps. The importer requires:

- `issue_created_at <= requirements_as_of < accepted_at <= acquired_at <= current_time`;
- a nonempty complete source inventory with exactly the snapshot's paths, UTF-8 byte lengths
  and SHA-256 hashes, with only supported regular files;
- unchanged source bytes, including line endings and unchanged configuration files;
- bounded readable requirements text, distinct from known solution/source/control aggregates;
- all existing current preparation gates: explicit rights policy, license evidence, configured
  repository/image/commands, supported risk and budgets, disjoint storage/worker scopes, oracle
  separation, exact strict patch reconstruction and preservation of original tests and controls.

The inventory does not replace the acquisition producer's trust boundary. This module proves
consistency with the supplied complete inventory, not authenticity of remote Git objects or that
a malicious producer listed every upstream file. The producer must capture the complete tree,
reject unsupported links/binary/oversized content, and attest the issue snapshot and accepted-fix
linkage honestly. No `complete: true` flag, omitted-path list or subdirectory scope is accepted.
There is no fallback that silently slices a repository or filters control files to make it fit.
The current product snapshot fetcher's filtering/rejection profile is not silently repurposed
as a historical acquisition guarantee.

`import_historical_task(request, *, settings, policy, protected_artifacts, output_root,
worker_root, now)` returns `ImportedHistoricalTask` with `status="IMPORTED_NOT_QUALIFIED"`,
`admitted=false`, `execution_authorized=false` and metadata references only. All validation
finishes before metadata writes. Existing source/oracle/reference/license/requirements artifacts
are read without rewriting their bytes. Identical inputs and clock produce idempotent metadata;
individual content-addressed writes are not a cross-artifact transaction, so an I/O failure may
leave partial immutable metadata without returning success. Errors are sanitized.

Rights and historical-time fields are trusted producer attestations, not machine-established
legal clearance or historical authenticity. The specification digest binds the producer's task
projection; it does not prove semantic equivalence to the original issue text. A future protected
acquisition/qualification driver must supply the exact authorized pre-solution evidence to
independent reviewers, retain exclusion reasons and run actual deterministic/model qualification.
Current qualification authority and the existing source-only worker-export boundary remain
mandatory after import. The import result grants neither export nor scoring access.

Tests use expressly synthetic acquisition records and toy text. They cover immutable bytes,
inventory completeness/mismatch, unsupported input, chronological inconsistencies, revision and
reference bindings, sanitized failures, current authorization and no writes on validation failure.
They do not qualify any catalog candidate or establish actual historical rights or correctness.
