"""Protected, read-only preparation. This neither qualifies a task nor permits execution."""

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import AwareDatetime, Field

from agentic_delivery.config import Settings
from agentic_delivery.domain.models import CommitSHA, Contract, NonEmpty
from agentic_delivery.evaluation.harness import HistoricalTask
from agentic_delivery.evaluation.qualification import Digest, Provenance, qualification_task_digest
from agentic_delivery.evaluation.synthetic_types import (
    SyntheticLicenseEvidence,
    SyntheticProvenance,
    SyntheticReferenceProvenance,
    SyntheticTask,
    SyntheticUsageAuthorization,
)
from agentic_delivery.execution.files import protected, safe_path, validate_files
from agentic_delivery.execution.verification import pytest_selectors
from agentic_delivery.policy.changes import check_candidate
from agentic_delivery.policy.engine import POLICY_VERSION, evaluate_intake
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json

if TYPE_CHECKING:
    from agentic_delivery.evaluation.historical_derivation import ReferenceDerivation
    from agentic_delivery.evaluation.historical_linkage import HistoricalLinkageEvidence

MAX_PATCH_BYTES = 1024 * 1024
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_PATCH_FILES = 50
MAX_HUNKS = 1000
_HUNK = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: [^\r\n]*)?\n")
_PATH = re.compile(r"[A-Za-z0-9_./-]{1,240}")


class PreparationRequest(Contract):
    schema_version: Literal[1]
    task_artifact: Digest
    provenance_artifact: Digest
    reference_provenance_artifact: Digest


class PreparationPolicy(Contract):
    """Trusted controller input, never inferred from a submitted record or agent output."""

    schema_version: Literal[1]
    policy_version: Literal["mvp-1"]
    authorized_issuers: tuple[NonEmpty, ...] = Field(min_length=1, max_length=100)
    approved_authorization_artifacts: tuple[Digest, ...] = Field(min_length=1, max_length=1000)


class LicenseEvidence(Contract):
    schema_version: Literal[1]
    repository: NonEmpty
    base_sha: CommitSHA
    source_snapshot_artifact: Digest
    license_id: Literal["MIT", "BSD-2-Clause", "BSD-3-Clause"]
    license_path: NonEmpty
    license_url: NonEmpty
    license_text_sha256: Digest


class UsageAuthorization(Contract):
    """A pinned controller attestation, not a machine determination of legal rights."""

    schema_version: Literal[1]
    issuer: NonEmpty
    decision: Literal["AUTHORIZED"]
    task_manifest_digest: Digest
    repository: NonEmpty
    base_sha: CommitSHA
    source_url: NonEmpty
    source_revision: CommitSHA
    issue_url: NonEmpty
    license_evidence_artifact: Digest
    rights_scope: Literal["REPOSITORY_FILES_DATASET_ISSUE_AND_MODEL_PROCESSING"]
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    rationale: NonEmpty = Field(min_length=40, max_length=4000)


class ReferenceProvenance(Contract):
    """Imported historical identity claims; preparation does not query GitHub to attest them."""

    schema_version: Literal[1]
    task_manifest_digest: Digest
    repository: NonEmpty
    base_sha: CommitSHA
    accepted_commit: CommitSHA
    accepted_commit_url: NonEmpty
    issue_url: NonEmpty
    source_snapshot_artifact: Digest
    oracle_artifact: Digest
    reference_snapshot_artifact: Digest
    reference_patch_artifact: Digest


class ReferenceProvenanceV2(Contract):
    """Explicit derived execution identity; never labels it the accepted Git tree."""

    schema_version: Literal[2]
    kind: Literal["historical-derived-reference"]
    task_manifest_digest: Digest
    repository: NonEmpty
    base_sha: CommitSHA
    accepted_commit: CommitSHA
    accepted_commit_url: NonEmpty
    issue_url: NonEmpty
    source_snapshot_artifact: Digest
    oracle_artifact: Digest
    reference_snapshot_artifact: Digest
    reference_patch_artifact: Digest
    derivation_artifact: Digest
    linkage_artifact: Digest
    derivation_authorization_artifact: Digest


def validate_derived_requirements(
    task: HistoricalTask, linkage: "HistoricalLinkageEvidence", artifacts: ArtifactStore
) -> None:
    """Require the captured pre-acceptance body and neutral title on every derived route."""
    _require(
        task.item.title == f"Historical issue #{linkage.issue_number}"
        and task.item.description
        == artifacts.get(linkage.requirements_artifact).decode("utf-8").strip(),
        "Derived task wording differs from captured issue requirements",
    )


def parse_reference_provenance(document: Any) -> ReferenceProvenance | ReferenceProvenanceV2:
    if isinstance(document, dict) and document.get("schema_version") == 2:
        return ReferenceProvenanceV2.model_validate(document)
    return ReferenceProvenance.model_validate(document)


def validate_derived_reference_provenance(
    reference: ReferenceProvenanceV2,
    *,
    protected_artifacts: ArtifactStore,
    worker_roots: tuple[Path, ...] | None = None,
    protected_paths: tuple[str, ...] | None = None,
    now: datetime | None = None,
) -> tuple["ReferenceDerivation", "HistoricalLinkageEvidence"]:
    """Reconstruct identity/content; scope/current policy require trusted caller inputs.

    Protected semantic readers have no worker scope or live policy and use content-only
    validation. Preparation and current authority must supply/revalidate both separately.
    """
    from agentic_delivery.evaluation.historical_derivation import (
        validate_reference_derivation,
        validate_reference_derivation_content,
    )
    from agentic_delivery.evaluation.historical_linkage import validate_historical_linkage

    reference = ReferenceProvenanceV2.model_validate(reference.model_dump(mode="json"))
    derivation = (
        validate_reference_derivation_content(
            reference.derivation_artifact, protected_artifacts=protected_artifacts
        )
        if worker_roots is None
        else validate_reference_derivation(
            reference.derivation_artifact,
            protected_artifacts=protected_artifacts,
            worker_roots=worker_roots,
        )
    )
    linkage = validate_historical_linkage(
        reference.linkage_artifact,
        protected_artifacts=protected_artifacts,
        derivation=derivation,
        now=now,
    )
    _require(
        reference.repository == derivation.repository
        and reference.base_sha == derivation.base_sha
        and reference.accepted_commit == derivation.accepted_commit
        and reference.accepted_commit_url
        == f"https://github.com/{derivation.repository}/commit/{derivation.accepted_commit}"
        and reference.issue_url == linkage.issue_url
        and reference.source_snapshot_artifact == derivation.source_snapshot_artifact
        and reference.oracle_artifact == derivation.oracle_artifact
        and reference.reference_patch_artifact == derivation.production_patch_artifact
        and reference.reference_snapshot_artifact == derivation.executable_reference_artifact,
        "Derived reference provenance bindings are inconsistent",
    )
    if protected_paths is not None:
        _require(
            all(not protected(change.path, protected_paths) for change in derivation.changes),
            "Derived reference changes currently protected paths",
        )
    return derivation, linkage


class PreparedQualification(Contract):
    schema_version: Literal[1] = 1
    status: Literal["PREPARED_NOT_QUALIFIED"] = "PREPARED_NOT_QUALIFIED"
    execution_authorized: Literal[False] = False
    admitted: Literal[False] = False
    request: PreparationRequest
    task_id: NonEmpty
    task_manifest_digest: Digest
    execution_config_digest: Digest
    preparation_policy_digest: Digest
    policy_version: NonEmpty
    baseline_snapshot_digest: Digest
    reference_snapshot_digest: Digest
    patch_binding_digest: Digest
    prepared_at: AwareDatetime


def parse_task(document: Any) -> HistoricalTask | SyntheticTask:
    if isinstance(document, dict) and "kind" in document:
        return SyntheticTask.model_validate(document)
    return HistoricalTask.model_validate(document)


def parse_provenance(document: Any) -> Provenance | SyntheticProvenance:
    if isinstance(document, dict) and "kind" in document:
        return SyntheticProvenance.model_validate(document)
    return Provenance.model_validate(document)


def parse_usage_authorization(document: Any) -> UsageAuthorization | SyntheticUsageAuthorization:
    if isinstance(document, dict) and "kind" in document:
        return SyntheticUsageAuthorization.model_validate(document)
    return UsageAuthorization.model_validate(document)


def prepared_rights_expiry(request: "PreparationRequest", artifacts: ArtifactStore) -> datetime:
    """Read frozen deadlines only after full current preparation has validated both pins.

    This helper grants no authority. Active guards also retain the exact request and
    policy/configuration digests that were validated at the effect boundary.
    """
    provenance = parse_provenance(_read(artifacts, request.provenance_artifact))
    parent = parse_usage_authorization(_read(artifacts, provenance.usage_authorization_artifact))
    document = _read(artifacts, request.reference_provenance_artifact)
    if not isinstance(document, dict) or document.get("schema_version") != 2:
        return parent.expires_at
    from agentic_delivery.evaluation.historical_authorization import DerivedReferenceAuthorization

    reference = ReferenceProvenanceV2.model_validate(document)
    derived = DerivedReferenceAuthorization.model_validate(
        _read(artifacts, reference.derivation_authorization_artifact)
    )
    return min(parent.expires_at, derived.expires_at)


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, "Duplicate JSON key")
        result[key] = value
    return result


def _constant(value: str) -> Any:
    raise ValueError("Nonfinite JSON value")


def _read(store: ArtifactStore, digest: str) -> Any:
    raw = store.get(digest)
    _require(0 < len(raw) <= MAX_JSON_BYTES, "JSON evidence exceeds preparation bounds")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_object, parse_constant=_constant)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("Invalid or excessively nested JSON evidence") from exc


def _files(store: ArtifactStore, digest: str) -> dict[str, str]:
    files = _read(store, digest)
    _require(
        isinstance(files, dict)
        and bool(files)
        and all(isinstance(k, str) and isinstance(v, str) for k, v in files.items()),
        "Snapshot must be a nonempty string mapping",
    )
    _validate_snapshot(files)
    return dict(files)


def _validate_snapshot(files: dict[str, str]) -> None:
    validate_files(files)
    folded: set[str] = set()
    for path, content in files.items():
        _require("\x00" not in content, "NUL content is outside the text snapshot profile")
        _require(path.casefold() not in folded, "Case-colliding snapshot paths")
        folded.add(path.casefold())
    _require(
        not any(
            "/".join(path.split("/")[:n]).casefold() in folded
            for path in files
            for n in range(1, len(path.split("/")))
        ),
        "Snapshot file/directory collision",
    )


def _patch_path(line: str, prefix: str, side: str) -> str | None:
    _require(line.startswith(prefix) and line.endswith("\n"), "Unsupported patch header")
    value = line[len(prefix) : -1]
    if value == "/dev/null":
        return None
    _require(value.startswith(side + "/"), "Patch path has wrong side prefix")
    path = value[2:]
    _require(_PATH.fullmatch(path) is not None, "Unsupported or ambiguous patch path")
    return safe_path(path)


def apply_reference_patch(source: dict[str, str], patch: bytes) -> dict[str, str]:
    """Apply bounded LF unified text diffs exactly in memory, with no fuzz or subprocess."""
    _validate_snapshot(source)
    _require(0 < len(patch) <= MAX_PATCH_BYTES, "Reference patch exceeds bounds")
    try:
        text = patch.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError("Reference patch must be UTF-8 text") from exc
    _require("\r" not in text and "\x00" not in text, "Only LF text patches are supported")
    lines = text.splitlines(keepends=True)
    _require(all(line.endswith("\n") for line in lines), "Unterminated patch line")
    result = dict(source)
    seen: set[str] = set()
    index, hunk_total = 0, 0
    while index < len(lines):
        _require(index + 1 < len(lines), "Incomplete patch file header")
        old = _patch_path(lines[index], "--- ", "a")
        new = _patch_path(lines[index + 1], "+++ ", "b")
        index += 2
        _require(old is not None or new is not None, "Patch has no file path")
        _require(old is None or new is None or old == new, "Renames are unsupported")
        path = old if old is not None else new
        assert path is not None
        _require(path not in seen and len(seen) < MAX_PATCH_FILES, "Duplicate/too many patch files")
        seen.add(path)
        _require((old is None) == (path not in source), "Patch source existence mismatch")
        original = source.get(path, "")
        _require(
            not original or (original.endswith("\n") and "\r" not in original),
            "Patched files must use LF and a final newline",
        )
        old_lines = original.splitlines(keepends=True)
        cursor, hunks = 0, 0
        output: list[str] = []
        while index < len(lines) and lines[index].startswith("@@ "):
            match = _HUNK.fullmatch(lines[index])
            _require(match is not None, "Malformed unified hunk")
            assert match is not None
            old_start, old_count, new_start, new_count = (
                int(match[1]),
                int(match[2] or "1"),
                int(match[3]),
                int(match[4] or "1"),
            )
            _require(old_count + new_count > 0, "Empty hunk is unsupported")
            position = old_start if old_count == 0 else old_start - 1
            new_position = new_start if new_count == 0 else new_start - 1
            _require(cursor <= position <= len(old_lines), "Overlapping/out-of-range hunk")
            output.extend(old_lines[cursor:position])
            _require(new_position == len(output), "Hunk target position mismatch")
            cursor, used_old, used_new = position, 0, 0
            index += 1
            while used_old < old_count or used_new < new_count:
                _require(index < len(lines), "Incomplete hunk body")
                line = lines[index]
                kind, content = line[:1], line[1:]
                _require(kind in {" ", "+", "-"}, "Unsupported hunk record")
                if kind in {" ", "-"}:
                    _require(
                        used_old < old_count
                        and cursor < len(old_lines)
                        and old_lines[cursor] == content,
                        "Patch context/removal differs from immutable source",
                    )
                    cursor += 1
                    used_old += 1
                if kind in {" ", "+"}:
                    _require(used_new < new_count, "Hunk target count exceeded")
                    output.append(content)
                    used_new += 1
                index += 1
            hunks += 1
            hunk_total += 1
            _require(hunk_total <= MAX_HUNKS, "Too many patch hunks")
        _require(hunks > 0, "Patch file has no hunks")
        output.extend(old_lines[cursor:])
        changed = "".join(output)
        if new is None:
            _require(changed == "", "Deletion leaves file content")
            del result[path]
        else:
            _require(changed != original, "Empty/no-op patch file")
            result[path] = changed
    _validate_snapshot(result)
    _require(result != source, "Reference patch makes no changes")
    return result


def _scopes(*paths: Path) -> None:
    roots = []
    for path in paths:
        absolute = path.absolute()
        _require(absolute.is_dir(), "Preparation scopes must be existing directories")
        for ancestor in (absolute, *absolute.parents):
            _require(
                not ancestor.is_symlink() and not ancestor.is_junction(),
                "Linked preparation scope is unsupported",
            )
        roots.append(absolute.resolve(strict=True))
    _require(
        all(
            not left.is_relative_to(right) and not right.is_relative_to(left)
            for n, left in enumerate(roots)
            for right in roots[n + 1 :]
        ),
        "Protected evidence, output and worker scopes must be disjoint",
    )


def prepare_qualification(
    request: PreparationRequest,
    *,
    settings: Settings,
    policy: PreparationPolicy,
    protected_artifacts: ArtifactStore,
    output_root: Path,
    worker_root: Path,
    now: datetime,
) -> PreparedQualification:
    """Validate protected imports without writes, exports, execution, reviews or admission.

    The caller owns settings, policy and the clock. Revalidate at future effect boundaries;
    a returned record does not protect against later configuration/filesystem changes.
    """
    request = PreparationRequest.model_validate(request.model_dump(mode="json"))
    policy = PreparationPolicy.model_validate(policy.model_dump(mode="json"))
    settings = Settings.model_validate(settings.model_dump(mode="json"))
    _scopes(protected_artifacts.root, output_root, worker_root)
    _require(now.tzinfo is not None and now.utcoffset() is not None, "Aware clock required")
    _require(policy.policy_version == POLICY_VERSION, "Preparation policy version is stale")
    task = parse_task(_read(protected_artifacts, request.task_artifact))
    provenance = parse_provenance(_read(protected_artifacts, request.provenance_artifact))
    _require(
        task.qualification_artifact == "0" * 64
        and task.qualification_mode in {"independent-agents-v1", "independent-agents-v2"}
        and len(task.reviewers) == 2,
        "Preparation requires a pending agent-mode draft with two reserved context IDs",
    )
    digest = qualification_task_digest(task.model_dump(mode="json"))
    repository = settings.repository(task.item.repository)
    for configured in settings.repositories:
        if configured.local_repository is not None:
            _scopes(protected_artifacts.root, output_root, configured.local_repository)
    repo = f"{repository.github_owner}/{repository.github_name}"
    _require(settings.admissions_enabled, "Operator admissions are disabled")
    _require(repository.model_data_authorized, "Repository model data authorization is absent")
    if isinstance(task, SyntheticTask):
        _require(isinstance(provenance, SyntheticProvenance), "Mixed task/provenance kinds")
        assert isinstance(provenance, SyntheticProvenance)
        _require(
            provenance.repository == repo
            and provenance.authoring_artifact == task.authoring_artifact
            and provenance.construction_revision == task.construction_revision
            and provenance.source_snapshot_artifact == task.snapshot_artifact
            and provenance.license_id == task.license_id,
            "Synthetic task/provenance differs from configured repository or construction",
        )
    else:
        _require(isinstance(provenance, Provenance), "Mixed task/provenance kinds")
        assert isinstance(provenance, Provenance)
        _require(
            task.repository_url == f"https://github.com/{repo}"
            and provenance.repository == repo
            and provenance.base_sha == task.base_sha
            and provenance.source_snapshot_artifact == task.snapshot_artifact
            and provenance.issue_url == task.issue_url
            and provenance.license_id == task.license_id
            and task.issue_url.startswith(f"https://github.com/{repo}/issues/"),
            "Task/provenance differs from configured repository or immutable base",
        )
    _require(task.image == repository.sandbox_image, "Image differs from pinned configuration")
    _require(evaluate_intake(task.item).allowed, "Task requires policy/risk escalation")
    _require(
        all(
            limit <= settings.budget.model_dump()[name]
            for name, limit in task.budget.model_dump().items()
        ),
        "Task budget exceeds operator limits",
    )
    _require(
        len(task.acceptance_commands) == len(task.regression_commands) == 1,
        "Preparation supports one acceptance and one regression profile",
    )
    _require(
        len({c.id for c in repository.commands}) == len(repository.commands),
        "Configured command identities are ambiguous",
    )
    for command in (*task.acceptance_commands, *task.regression_commands):
        _require(command in repository.commands, "Command differs from operator configuration")
        _require(bool(pytest_selectors(command.argv)), "Explicit pytest selectors required")
    _require(
        task.acceptance_commands[0].id != task.regression_commands[0].id,
        "Acceptance and regression command identities overlap",
    )
    _require(task.reference_snapshot_artifact is not None, "Reference snapshot is missing")
    assert task.reference_snapshot_artifact is not None
    source = _files(protected_artifacts, task.snapshot_artifact)
    oracle = _files(protected_artifacts, task.oracle_artifact)
    declared = _files(protected_artifacts, task.reference_snapshot_artifact)
    _require(
        not {p.casefold() for p in source} & {p.casefold() for p in oracle},
        "Oracle collides with source",
    )
    baseline = {**source, **oracle}
    _validate_snapshot(baseline)
    _require(
        all(
            path.endswith(".py")
            and _test_path(path)
            and not protected(path, repository.protected_paths)
            for path in oracle
        ),
        "Oracle must contain only test Python files without runner/control overrides",
    )
    if isinstance(task, SyntheticTask):
        assert isinstance(provenance, SyntheticProvenance)
        license_path = _synthetic_rights(
            task, provenance, request, policy, protected_artifacts, source, repo, digest, now
        )
    else:
        assert isinstance(provenance, Provenance)
        reference = parse_reference_provenance(
            _read(protected_artifacts, request.reference_provenance_artifact)
        )
        if isinstance(reference, ReferenceProvenanceV2):
            _require(
                task.qualification_mode == "independent-agents-v2",
                "Derived references require current qualification protocol",
            )
            derivation, linkage = validate_derived_reference_provenance(
                reference,
                protected_artifacts=protected_artifacts,
                worker_roots=(
                    worker_root,
                    *(r.local_repository for r in settings.repositories if r.local_repository),
                ),
                protected_paths=repository.protected_paths,
                now=now,
            )
            validate_derived_requirements(task, linkage, protected_artifacts)
            _require(
                pytest_selectors(task.acceptance_commands[0].argv)
                == derivation.acceptance_selectors,
                "Acceptance selectors differ from immutable derivation",
            )
            _require(
                all(
                    selector.split("::", 1)[0] in source and _test_path(selector.split("::", 1)[0])
                    for selector in pytest_selectors(task.regression_commands[0].argv)
                ),
                "Derived regression commands must select original source test files",
            )
        license_record = LicenseEvidence.model_validate(
            _read(protected_artifacts, provenance.license_evidence_artifact)
        )
        license_path = safe_path(license_record.license_path)
        _require(
            license_record.repository == repo
            and license_record.base_sha == task.base_sha
            and license_record.source_snapshot_artifact == task.snapshot_artifact
            and license_record.license_id == task.license_id
            and license_record.license_url == provenance.license_url
            and license_record.license_url
            == f"https://github.com/{repo}/blob/{task.base_sha}/{license_path}"
            and len(source.get(license_path, "").strip()) >= 80
            and hashlib.sha256(source.get(license_path, "").encode()).hexdigest()
            == license_record.license_text_sha256,
            "License record does not bind substantive immutable source license text",
        )
        _require(
            provenance.usage_authorization_artifact in policy.approved_authorization_artifacts,
            "Usage authorization is not pinned by the trusted preparation policy",
        )
        authorization = UsageAuthorization.model_validate(
            _read(protected_artifacts, provenance.usage_authorization_artifact)
        )
        _require(
            authorization.issuer in policy.authorized_issuers
            and authorization.task_manifest_digest == digest
            and authorization.repository == repo
            and authorization.base_sha == task.base_sha
            and authorization.source_url == provenance.source_url
            and authorization.source_revision == provenance.source_revision
            and authorization.issue_url == task.issue_url
            and authorization.license_evidence_artifact == provenance.license_evidence_artifact
            and authorization.rights_scope == provenance.rights_scope
            and authorization.issued_at <= now < authorization.expires_at,
            "Usage authorization is stale, unsupported or bound to different inputs",
        )
        if isinstance(reference, ReferenceProvenanceV2):
            from agentic_delivery.evaluation.historical_authorization import (
                validate_derived_authorization,
            )

            validate_derived_authorization(
                reference.derivation_authorization_artifact,
                protected_artifacts=protected_artifacts,
                derivation=derivation,
                parent_authorization_artifact=provenance.usage_authorization_artifact,
                task_manifest_digest=digest,
                linkage_artifact=reference.linkage_artifact,
                now=now,
                policy=policy,
            )
        _require(
            reference.task_manifest_digest == digest
            and reference.repository == repo
            and reference.base_sha == task.base_sha
            and reference.accepted_commit != task.base_sha
            and reference.accepted_commit_url
            == f"https://github.com/{repo}/commit/{reference.accepted_commit}"
            and reference.issue_url == task.issue_url
            and reference.source_snapshot_artifact == task.snapshot_artifact
            and reference.oracle_artifact == task.oracle_artifact
            and reference.reference_snapshot_artifact == task.reference_snapshot_artifact
            and reference.reference_patch_artifact == task.reference_patch_artifact,
            "Reference provenance does not bind this immutable task",
        )
    patched = apply_reference_patch(source, protected_artifacts.get(task.reference_patch_artifact))
    regression_paths = tuple(
        selector.split("::", 1)[0]
        for selector in pytest_selectors(task.regression_commands[0].argv)
    )
    for path in source.keys() | patched.keys():
        if (
            protected(path, repository.protected_paths)
            or path == license_path
            or (
                path in source
                and (
                    _test_path(path)
                    or any(path == p or path.startswith(p + "/") for p in regression_paths)
                )
            )
        ):
            _require(
                source.get(path) == patched.get(path), "Reference changes protected controls/tests"
            )
    _require(not set(patched) & set(oracle), "Reference creates an oracle collision")
    try:
        check_candidate(source, patched)
    except SyntaxError:
        # SyntaxError.text contains protected reference code; do not expose it to callers.
        raise ValueError("Reference code is outside the supported Python syntax profile") from None
    reconstructed = {**patched, **oracle}
    _validate_snapshot(reconstructed)
    _require(reconstructed == declared, "Applied patch plus oracle differs from reference snapshot")
    return PreparedQualification(
        request=request,
        task_id=task.id,
        task_manifest_digest=digest,
        execution_config_digest=settings.execution_digest(repository.id),
        preparation_policy_digest=digest_json(policy.model_dump(mode="json")),
        policy_version=POLICY_VERSION,
        baseline_snapshot_digest=digest_json(baseline),
        reference_snapshot_digest=digest_json(reconstructed),
        patch_binding_digest=digest_json(
            [
                task.snapshot_artifact,
                task.reference_patch_artifact,
                task.reference_snapshot_artifact,
            ]
        ),
        prepared_at=now,
    )


def _synthetic_rights(
    task: SyntheticTask,
    provenance: SyntheticProvenance,
    request: PreparationRequest,
    policy: PreparationPolicy,
    store: ArtifactStore,
    source: dict[str, str],
    repo: str,
    digest: str,
    now: datetime,
) -> str:
    license_record = SyntheticLicenseEvidence.model_validate(
        _read(store, provenance.license_evidence_artifact)
    )
    license_path = safe_path(license_record.license_path)
    _require(
        license_record.repository == repo
        and license_record.construction_revision == task.construction_revision
        and license_record.source_snapshot_artifact == task.snapshot_artifact
        and license_record.license_id == task.license_id
        and len(source.get(license_path, "").strip()) >= 80
        and hashlib.sha256(source.get(license_path, "").encode()).hexdigest()
        == license_record.license_text_sha256,
        "Synthetic license does not bind substantive local source license text",
    )
    _require(
        provenance.usage_authorization_artifact in policy.approved_authorization_artifacts,
        "Synthetic usage authorization is not pinned by trusted policy",
    )
    authorization = parse_usage_authorization(_read(store, provenance.usage_authorization_artifact))
    _require(isinstance(authorization, SyntheticUsageAuthorization), "Mixed authorization kind")
    assert isinstance(authorization, SyntheticUsageAuthorization)
    _require(
        authorization.issuer in policy.authorized_issuers
        and authorization.authoring_artifact == task.authoring_artifact
        and authorization.task_manifest_digest == digest
        and authorization.repository == repo
        and authorization.construction_revision == task.construction_revision
        and authorization.license_evidence_artifact == provenance.license_evidence_artifact
        and authorization.rights_scope == provenance.rights_scope
        and authorization.issued_at <= now < authorization.expires_at,
        "Synthetic usage authorization is stale or bound to different inputs",
    )
    reference = SyntheticReferenceProvenance.model_validate(
        _read(store, request.reference_provenance_artifact)
    )
    _require(
        reference.task_manifest_digest == digest
        and reference.repository == repo
        and reference.construction_revision == task.construction_revision
        and reference.source_snapshot_artifact == task.snapshot_artifact
        and reference.oracle_artifact == task.oracle_artifact
        and reference.reference_snapshot_artifact == task.reference_snapshot_artifact
        and reference.reference_patch_artifact == task.reference_patch_artifact,
        "Authored fixture reference does not bind this synthetic task",
    )
    return license_path


def _test_path(path: str) -> bool:
    parts = path.lower().split("/")
    return any(p in {"tests", "test"} for p in parts[:-1]) or (
        parts[-1].startswith("test_") or parts[-1].endswith("_test.py")
    )
