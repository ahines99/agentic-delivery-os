# Historical input provenance and processing

The user's hands-off instruction authorizes automated project work and independent
agent qualification. It does not require two human curators. The trusted evaluation
controller may make a finite processing decision using supported upstream evidence
and the existing `UsageAuthorization` / `PreparationPolicy` contracts. It must not
invent ownership, human approval or permission to redistribute a dataset.

## Evidence needed for an actual task

Keep these records in protected evaluator storage, with exact artifact digests:

| Component | Required evidence |
| --- | --- |
| Source | Complete acquired snapshot, pinned license bytes, relevant notices and exceptions. Preserve required notices in copies and model inputs. |
| Issue | Frozen title/body, provider identity and edit-history observations, contribution time, applicable repository licensing/contribution terms, and any discovered exceptions or unsupported third-party material. |
| Task projection | Exact requirement/oracle inputs and their derivation from the issue; separately assess semantic fidelity. A digest alone does not establish that fidelity. |
| Model processing | Exact authorized input set/projection, provider/model/configuration, applicable terms, finite purpose and expiry, and existing metered runtime/model grants. |
| Controller decision | Existing project authority, trusted issuer and allowlisted authorization digest, supported rationale and supplementary evidence references. |

The current preparation contract checks the source license binding and a trusted
authorization attestation. It does not machine-verify the whole contribution and
provider rights chain. Supplementary evidence must remain distinguishable from those
enforced fields; adding a digest to free text does not create a new validator.

GitHub's contribution terms provide a possible repository-license basis for content
added to a licensed repository, subject to superseding agreements. This is a basis
to investigate for an issue, not a conclusion that every public issue, attachment
or third-party excerpt is covered. Public visibility and a displayed SPDX label
alone are insufficient. [GitHub Terms, section D.6](https://docs.github.com/en/site-policy/github-terms/github-terms-of-service),
[GitHub license detection](https://docs.github.com/en/rest/licenses/licenses).

Covered MIT material permits copying and use with its notice condition. The project
must retain the actual notice; matching license text does not determine coverage of
every other file or contribution. [MIT license](https://choosealicense.com/licenses/mit/).

For the implemented direct Anthropic Messages broker, record standard commercial
API processing and its documented retention exceptions. Do not claim ZDR, verified
private account settings or provider deletion at the end of a local grant. Existing
project policy does not require ZDR or a new human approval for every already
authorized task. An unknown account preference can remain unknown without inventing
a stricter release gate. Rights to the submitted input remain required.
[Commercial Terms](https://www.anthropic.com/legal/commercial-terms),
[API retention](https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data).

Use public, necessary information and bounded API requests; exclude unnecessary
profile data and unsupported issue extras without rewriting the task requirements.
If relying on GitHub's research permission, observe its open-access publication
condition and separate personal-information restrictions. No corpus release is
authorized by an internal evaluation grant.
[GitHub Acceptable Use Policies, sections 7–8](https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies).

## Recorded protected license observations

For the acquired `tkem/cachetools` baseline at
`13bb86a55e36e501cf0b3e4c35db516ed9409fd7`, the protected producer compared the
root license against SPDX's MIT text. The grant, conditions and disclaimer matched
after whitespace normalization, with the copyright notice retained. It wrote the
existing typed `LicenseEvidence` bound to the exact snapshot and license bytes.

Two subsequent public API reads reported the latest `LICENSE` change reachable from
that base at `1b704d0bd4b1656109f20905d76f1564a185afd7`, with committer timestamp
2026-01-25T14:39:06Z, before the candidate issue's recorded creation. License bytes
at that change matched the baseline exactly, including their Git blob hash.
These are GitHub history and Git timestamp observations, not independent proof of
wall-clock publication or issue contribution coverage.

No historical source, issue, oracle or reference text was printed into implementation
conversation. No repository code or model ran. These observations are evidence
ingredients only: no usage authorization, task import or qualification resulted.

For accepted changes that modify original tests, [ADR-013](adr/ADR-013-derived-historical-reference.md)
specifies explicit derived-reference provenance and source-layout execution support.
That design remains unimplemented; the existing importer still refuses such changes.
