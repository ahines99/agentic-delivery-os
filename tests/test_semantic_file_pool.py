"""Owned typed shapes only: no actual qualification, scoring, Docker or provider evidence."""

import hashlib
import json
import warnings

import pytest

from agentic_delivery.domain.models import WorkItem
from agentic_delivery.evaluation import semantic_file_pool as pool
from agentic_delivery.evaluation.semantic_scoring import (
    FrozenOwnedSemanticEvidence,
    FrozenSemanticEvidence,
    SemanticExecution,
    SemanticScoringContext,
)
from agentic_delivery.storage.store import digest_json


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False).encode()


def ref(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def context_for(purpose):
    shared = "\n  # owned Ω / 🙂\r\n\tvalue = 'quoted \\\" text'\r\n\n"
    source = {"app.py": "VALUE = 1\r\n", "notes.txt": shared, "empty.txt": ""}
    candidate = {**source, "app.py": "VALUE = 2\r\n", "copies/notes.txt": shared}
    oracle = {"tests/test_owned.py": "def test_owned():\n    assert True\n", "notes.txt": shared}
    common = dict(
        source_snapshot_artifact=ref(source),
        source_files=source,
        candidate_artifact=ref(candidate),
        candidate_digest=digest_json(candidate),
        candidate_files=candidate,
        oracle_artifact=ref(oracle),
        oracle_files=oracle,
        diff="\n owned unchanged diff string \r\n",
        account_id="owned-structural-codec-only",
        executions=tuple(
            SemanticExecution(
                stage=stage,
                receipt_artifact=character * 64,
                command_id=stage,
                nodes=("tests/test_owned.py::test_owned",),
                phases=(("tests/test_owned.py::test_owned", "call", "passed"),),
            )
            for stage, character in (("acceptance", "1"), ("regression", "2"))
        ),
        rubric_artifact="3" * 64,
        rubric_text="Owned codec shape, not a judgment or executed evidence.",
    )
    if purpose == "HISTORICAL_CANDIDATE":
        item = WorkItem(
            id="owned-historical-shaped-toy",
            title="Owned codec example",
            description="Original bytes only; not historical material or admission.",
            repository="owned/toy",
            risk_tier=1,
            acceptance_criteria=(
                {"id": "AC-1", "description": "Retain bytes", "verification_type": "unit_test"},
            ),
        )
        evidence = FrozenSemanticEvidence(
            **common,
            task_id=item.id,
            task_manifest_digest="4" * 64,
            qualification_artifact="5" * 64,
            split="development",
            task_spec=item,
            deterministic_evidence_digest="6" * 64,
            scoring_binding_artifact="7" * 64,
            attempt_binding_artifact="8" * 64,
            campaign_artifact="9" * 64,
        )
    else:
        evidence = FrozenOwnedSemanticEvidence(
            **common,
            subject_id="owned-codec-only",
            subject_artifact="4" * 64,
            authorship="Original structural test data with no executed operations.",
            requirements="Retain the original content.",
            criteria=({"id": "AC-1", "description": "Retain bytes"},),
            runtime_evidence_artifact="5" * 64,
            runtime_binding_artifact="6" * 64,
            request_digest="7" * 64,
            authorization_digest="8" * 64,
            executed_snapshot_digest="9" * 64,
            operation_receipt_digests=("a" * 64, "b" * 64, "c" * 64),
            image="sha256:" + "d" * 64,
        )
    return SemanticScoringContext(
        purpose=purpose,
        stage="scorer_a",
        context_id="owned-codec-a",
        evidence=evidence,
        evidence_digest=digest_json(evidence.model_dump(mode="json")),
    )


@pytest.fixture(params=["HISTORICAL_CANDIDATE", "OWNED_DEVELOPMENT_CALIBRATION"])
def context(request):
    return context_for(request.param)


def change_evidence(context, **changes):
    evidence = context.evidence.model_copy(update=changes)
    return context.model_copy(
        update={
            "evidence": evidence,
            "evidence_digest": digest_json(evidence.model_dump(mode="json")),
        }
    )


def test_exact_roundtrip_preserves_all_roles_metadata_and_original_digest(context):
    before = context.model_dump(mode="json")
    payload = pool.encode_semantic_file_pool(context)
    document = json.loads(payload)
    restored = pool.decode_semantic_file_pool(payload)
    assert restored == context and restored.model_dump(mode="json") == before
    assert pool.encode_semantic_file_pool(restored) == payload
    assert document["original_context_digest"] == digest_json(before)
    assert context.model_dump(mode="json") == before
    assert set(document["manifests"]) == set(pool.ROLES)
    assert not set(pool.ROLES) & document["context_without_file_maps"]["evidence"].keys()
    for role in pool.ROLES:
        for path, content in getattr(context.evidence, role).items():
            key = document["manifests"][role][path]
            assert key == hashlib.sha256(content.encode()).hexdigest()
            assert document["blobs"][key].encode() == content.encode()
    empty = hashlib.sha256(b"").hexdigest()
    assert document["blobs"][empty] == ""
    shared = document["manifests"]["source_files"]["notes.txt"]
    assert document["manifests"]["candidate_files"]["copies/notes.txt"] == shared
    assert document["manifests"]["oracle_files"]["notes.txt"] == shared
    assert (
        document["manifests"]["source_files"]["app.py"]
        != document["manifests"]["candidate_files"]["app.py"]
    )
    for field, value in document["context_without_file_maps"]["evidence"].items():
        assert value == before["evidence"][field]
    assert not {"admitted", "strict_success", "authority_validated"} & document.keys()


@pytest.mark.parametrize(
    "fault",
    [
        "digest",
        "missing-role",
        "extra-role",
        "missing-blob",
        "extra-blob",
        "bad-blob-hash",
        "bad-reference",
        "missing-path",
        "extra-path",
        "unsafe-path",
        "metadata-file-map",
        "extra-field",
        "profile",
        "version",
        "bool-version",
        "bad-type",
        "purpose",
        "coercion",
        "evidence-digest",
        "candidate-digest",
    ],
)
def test_mutated_envelope_is_never_a_lossless_context(context, fault):
    document = json.loads(pool.encode_semantic_file_pool(context))
    files = document["manifests"]["source_files"]
    first = next(iter(document["blobs"]))
    metadata = document["context_without_file_maps"]
    if fault == "digest":
        document["original_context_digest"] = "f" * 64
    elif fault == "missing-role":
        document["manifests"].pop("oracle_files")
    elif fault == "extra-role":
        document["manifests"]["reference_files"] = {}
    elif fault == "missing-blob":
        document["blobs"].pop(first)
    elif fault == "extra-blob":
        document["blobs"][hashlib.sha256(b"unused private value").hexdigest()] = (
            "unused private value"
        )
    elif fault == "bad-blob-hash":
        document["blobs"][first] += "changed"
    elif fault == "bad-reference":
        files["app.py"] = "F" * 64
    elif fault == "missing-path":
        files.pop("notes.txt")  # Shared content remains used by other roles.
    elif fault == "extra-path":
        files["unexpected.py"] = first
    elif fault == "unsafe-path":
        files["../outside.py"] = files.pop("app.py")
    elif fault == "metadata-file-map":
        metadata["evidence"]["source_files"] = {}
    elif fault == "extra-field":
        document["authorization"] = True
    elif fault == "profile":
        document["profile"] = "latest"
    elif fault == "version":
        document["schema_version"] = 2
    elif fault == "bool-version":
        document["schema_version"] = True
    elif fault == "bad-type":
        document["blobs"][first] = 3
    elif fault == "purpose":
        metadata["purpose"] = (
            "HISTORICAL_CANDIDATE"
            if context.purpose != "HISTORICAL_CANDIDATE"
            else "OWNED_DEVELOPMENT_CALIBRATION"
        )
    elif fault == "coercion":
        metadata["context_id"] = " padded "
    elif fault == "evidence-digest":
        metadata["evidence_digest"] = "f" * 64
    else:
        metadata["evidence"]["candidate_digest"] = "f" * 64
    with pytest.raises(pool.SemanticFilePoolFailure):
        pool.decode_semantic_file_pool(encoded(document))


@pytest.mark.parametrize("position", ["root", "metadata", "path", "blob"])
def test_duplicate_json_keys_rejected_even_identical_values(context, position):
    payload = pool.encode_semantic_file_pool(context)
    document = json.loads(payload)
    if position == "root":
        key, value = "profile", document["profile"]
    elif position == "metadata":
        key, value = "context_id", document["context_without_file_maps"]["context_id"]
    elif position == "path":
        key, value = "app.py", document["manifests"]["source_files"]["app.py"]
    else:
        key, value = next(iter(document["blobs"].items()))
    pair = encoded(key) + b": " + encoded(value)
    assert pair in payload
    payload = payload.replace(pair, pair + b", " + pair, 1)
    with pytest.raises(pool.SemanticFilePoolFailure):
        pool.decode_semantic_file_pool(payload)


@pytest.mark.parametrize("fault", ["newline", "compact", "order", "utf8", "nonfinite", "text"])
def test_serialization_is_exact_and_canonical(context, fault):
    payload = pool.encode_semantic_file_pool(context)
    document = json.loads(payload)
    if fault == "newline":
        payload += b"\n"
    elif fault == "compact":
        payload = json.dumps(document, separators=(",", ":"), sort_keys=True).encode()
    elif fault == "order":
        payload = json.dumps(dict(reversed(list(document.items())))).encode()
    elif fault == "utf8":
        payload = json.dumps(document, sort_keys=True, ensure_ascii=False).encode()
    elif fault == "nonfinite":
        payload = payload[:-1] + b', "unknown": NaN}'
    else:
        payload = payload.decode()
    with pytest.raises(pool.SemanticFilePoolFailure):
        pool.decode_semantic_file_pool(payload)


def test_expansion_is_refused_before_context_construction(context, monkeypatch):
    document = json.loads(pool.encode_semantic_file_pool(context))
    content = "x" * (200 * 1024)
    key = hashlib.sha256(content.encode()).hexdigest()
    document["blobs"] = {key: content}
    document["manifests"] = {role: {"large.py": key} for role in pool.ROLES}
    payload = encoded(document)
    assert len(payload) < pool.MAX_CONTEXT_BYTES
    invoked = []

    def forbidden(*args, **kwargs):
        invoked.append(True)
        raise AssertionError("Expanded context must not be constructed")

    monkeypatch.setattr(pool, "_checked_context", forbidden)
    with pytest.raises(pool.SemanticFilePoolFailure):
        pool.decode_semantic_file_pool(payload)
    assert invoked == []


def test_exact_existing_context_size_boundary_is_preserved(context):
    sized = change_evidence(context, diff="")
    remaining = pool.MAX_CONTEXT_BYTES - len(encoded(sized.model_dump(mode="json")))
    sized = change_evidence(sized, diff="x" * remaining)
    assert len(encoded(sized.model_dump(mode="json"))) == pool.MAX_CONTEXT_BYTES
    assert pool.decode_semantic_file_pool(pool.encode_semantic_file_pool(sized)) == sized
    with pytest.raises(pool.SemanticFilePoolFailure):
        pool.encode_semantic_file_pool(change_evidence(sized, diff="x" * (remaining + 1)))


@pytest.mark.parametrize(
    "content", ["\ud800", "x" * (pool.MAX_FILE_BYTES + 1)], ids=["surrogate", "oversized"]
)
def test_invalid_utf8_or_oversized_file_is_denied(context, content):
    # No hashing of this invalid authored input is asserted as valid provenance.
    evidence = context.evidence.model_copy(update={"source_files": {"bad.py": content}})
    broken = context.model_copy(update={"evidence": evidence})
    with pytest.raises(pool.SemanticFilePoolFailure):
        pool.encode_semantic_file_pool(broken)


def test_wire_bound_and_deeply_nested_input_are_sanitized():
    for payload in (b"x" * (pool.MAX_ENVELOPE_BYTES + 1), b"[" * 2000 + b"]" * 2000, b""):
        with pytest.raises(pool.SemanticFilePoolFailure, match="cannot be reconstructed"):
            pool.decode_semantic_file_pool(payload)


def test_invalid_typed_input_emits_no_content_or_serializer_warning(context):
    marker = "OWNED-CONTENT-MUST-NOT-APPEAR-IN-DIAGNOSTICS"
    evidence = context.evidence.model_copy(update={"source_files": {"bad.py": {marker: True}}})
    broken = context.model_copy(update={"evidence": evidence})
    with (
        warnings.catch_warnings(record=True) as emitted,
        pytest.raises(pool.SemanticFilePoolFailure) as error,
    ):
        pool.encode_semantic_file_pool(broken)
    assert emitted == [] and marker not in str(error.value)


def test_pooling_does_not_claim_every_context_becomes_smaller(context):
    small = len(pool.encode_semantic_file_pool(context))
    assert small > len(encoded(context.model_dump(mode="json")))
    repeated = "# owned repeated content\n" * 1000
    files = {"same.txt": repeated}
    large = change_evidence(
        context,
        source_files=files,
        candidate_files=files,
        oracle_files=files,
        candidate_digest=digest_json(files),
    )
    packed = pool.encode_semantic_file_pool(large)
    assert len(packed) < len(encoded(large.model_dump(mode="json")))
    assert pool.decode_semantic_file_pool(packed) == large
