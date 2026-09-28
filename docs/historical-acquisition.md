# Protected public baseline acquisition

`evaluation.historical_acquisition.acquire_public_github_baseline` implements one part
of historical evaluation preparation: a complete, bounded, public GitHub baseline at
an explicit immutable commit. It returns `BaselineAcquisition` metadata and protected
artifact references with status `BASELINE_ONLY_NOT_IMPORTED`. It does not fetch issue
requirements, accepted commits, reference patches, oracle tests, rights evidence, or
the rest of a `HistoricalAcquisitionEvidence` bundle. It does not qualify, admit, score,
execute repository code, call a model, or authorize spending.

The caller selects the commit. The existing `base_sha` field and baseline result
name are retained for compatibility; they do not establish that a commit predates
a particular fix. A protected producer may reuse this complete Git read mechanism
to acquire an explicitly identified accepted commit, but must wrap it as accepted
reference evidence, retain the distinct historical baseline identity, and exclude
its contents from model/worker inputs. Such a capture is not a derived executable
reference, oracle or imported historical task; [ADR-013](adr/ADR-013-derived-historical-reference.md)
specifies the separate pending derivation work.

The request requires a strict `owner/repository` and lowercase 40-hex commit SHA. The
acquirer first checks public repository metadata, then requests that commit, its recursive
tree, and each unique blob. The origin is fixed to `https://api.github.com`; returned
URLs are never followed. Redirects, non-200 responses including 403/429, compression,
malformed JSON, duplicate JSON keys, timeouts, and exceeded limits refuse the entire
acquisition. There are no retries, credential lookups, GitHub PAT fallbacks, cookies, or
environment proxies in the default transport. An injected `httpx.AsyncClient` is a
trusted test/transport dependency; its default auth, headers, cookies and query parameters
are not copied into requests. Its custom transport/event hooks remain trusted code.

GitHub documents that recursive trees may be truncated, and public tree/blob reads can
be unauthenticated. This implementation refuses truncation instead of silently dropping
entries or extending its request budget. Its fixed REST header is `2022-11-28`.
[GitHub tree API](https://docs.github.com/en/rest/git/trees#get-a-tree),
[GitHub blob API](https://docs.github.com/en/rest/git/blobs#get-a-blob).

The complete directory structure is reconstructed using Git tree ordering, modes and
child object IDs. Every reconstructed directory hash must match the recursively returned
tree, including the root SHA returned for the requested commit. Each blob must have the
exact declared size and SHA-1 of `blob <byte-length>\0<bytes>`. These checks detect omitted
entries, altered content and inconsistent trees. The commit-to-root-tree relationship is
still an assertion from the fixed GitHub HTTPS endpoint; this code does not reconstruct
the full commit object, verify author signatures, or authenticate arbitrary artifact
writers. Git object hashes bind bytes, not license rights or trustworthiness.
[Git object representation](https://git-scm.com/book/en/v2/Git-Internals-Git-Objects).

Only full repositories fitting the current text profile are accepted:

| Limit | Default / hard maximum |
| --- | --- |
| Regular files | 1,000 |
| File bytes | 256 KiB |
| Total file bytes | 8 MiB |
| Recursive entries, including directories | 2,000 |
| Path characters | 240 |
| Requests | 1,003: three metadata reads plus at most 1,000 unique blobs |
| Single response bytes | 2 MiB |
| Total transferred response bytes | 16 MiB |
| Per-request time | 15 seconds / 30 seconds |
| Entire acquisition time | 120 seconds / 300 seconds |

Callers may lower byte/file/request ceilings but cannot raise them above the profile.
The protected artifact store's own size limit also applies to serialized snapshot and
inventory; JSON overhead can cause a smaller repository to be refused. Unauthenticated
GitHub rate limits may prevent even an otherwise eligible baseline. Bulk transport for
a future campaign needs its own bounded design; this implementation does not substitute
product credentials or silently switch transport.

An optional `donor: BaselineAcquisition` lets a subsequent acquisition reuse exact
protected bytes. Both donor artifacts must exist in the same supplied protected store.
Their content digests, complete Git tree, per-path SHA-256 and byte lengths, full source
inventory, text profile and aggregate size are revalidated before network requests.
The repository name and fresh numeric repository identity must match the donor.
This supplies bytes only; it transfers no rights, historical authority or admission.

Every target still receives three fresh reads: public repository metadata, the requested
commit and its complete recursive tree. Only bytes whose recomputed Git blob SHA and
length match a fresh target entry can replace a blob download. Target paths and modes
come exclusively from the freshly verified tree. Removed paths disappear; renamed paths
can reuse identical bytes. Unmatched blobs are fetched normally. An identical target
therefore needs three requests, and two changed unique blobs need five, subject to all
existing limits. An invalid donor rejects the acquisition instead of silently fetching
a replacement. The default without a donor, serialized result fields, and snapshot and
inventory encoding remain unchanged; only the allowed request minimum is now three.

All regular-file bytes must decode as UTF-8 and round-trip unchanged. NUL, DEL, and
non-whitespace ASCII control characters are rejected as binary content. Newline style,
Unicode, BOMs, empty files, original tests, configurations and dependency files are
preserved. There are no filename/content filters or extension allowlists. Any unsafe
path, duplicate, case/NFC collision, symlink, submodule, special entry, binary blob or
oversized member rejects the whole baseline. Git LFS pointers are ordinary committed
text; external LFS objects are not downloaded. Empty directories, executable modes,
Git SHAs, byte lengths and content SHA-256 digests remain in the protected inventory.
The existing `SourceInventoryEntry` contracts describe each regular file for a later
historical-import producer; they do not by themselves constitute acquisition authority.

The trusted caller must pass a **nonempty** `worker_roots` tuple covering every relevant
worker, checkout, repository and worktree scope. Protected storage must be disjoint from
all supplied scopes in both directions. This is a caller-supplied scope check, not an
authentication system or discovery of every filesystem consumer. Keep protected source
outside interactive implementation-agent context and campaign builder/reviewer inputs.
Only the separately authorized evaluator may inspect these artifacts under ADR-010.

No artifact is written until all network responses, path/content checks and serialized
sizes pass. Snapshot and inventory use content-addressed writes; an I/O failure between
those writes may leave an unreferenced protected artifact but never returns partial
success. Exceptions contain a constant safe message, not upstream text, source contents,
headers or credentials. Cancellation propagates and response streams close.

The new tests use synthetic Git objects and HTTP transports. They cover exact bytes,
full-tree omission/tampering, unsupported entries, collisions, credentials/default-header
isolation, redirects, duplicate JSON, response/file/total/request limits, timeouts and
cancellation. Those tests fetch no actual historical payload. A complete rights-authorized
historical bundle and qualification remain separate from both the tests and the recorded
baseline below.

## Recorded public baseline acquisition

After the focused tests and independent review, a bounded credential-free run acquired
`tkem/cachetools` at `13bb86a55e36e501cf0b3e4c35db516ed9409fd7`. Its 43 regular files
contain 230,124 source bytes. All tree/blob checks passed; 46 public read requests
transferred 347,077 bytes. Source and inventory remain in evaluator-only storage.
The private cached check verified the same artifacts without a network request.

The run used stricter ceilings than the general profile: 64 requests/files, 64 KiB
per file, 512 KiB source/individual response, 2 MiB total transfer and 120 seconds.
No repository code or model ran. Status remains **BASELINE_ONLY_NOT_IMPORTED**:
this is a replacement lead, not a catalog promotion, rights authorization, verified
historical task base, oracle/reference reconstruction, imported task or qualification.

Subsequent protected [license observations](historical-input-provenance.md#recorded-protected-license-observations)
bind the baseline's MIT text and provider-reported license history. They do not supply
the remaining issue contribution, task projection or processing authorization evidence.
