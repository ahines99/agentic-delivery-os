"""Pure reversible file pooling, not evidence authentication or an enabled model profile."""

import hashlib
import json
from itertools import chain
from typing import Any, Literal

from pydantic import Field

from agentic_delivery.domain.models import Contract
from agentic_delivery.evaluation.qualification import Digest
from agentic_delivery.evaluation.semantic_scoring import MAX_CONTEXT_BYTES, SemanticScoringContext
from agentic_delivery.execution.files import MAX_FILE_BYTES, MAX_FILES, safe_path, validate_files
from agentic_delivery.storage.store import digest_json

PROFILE = "lossless-file-pool-v1"
MAX_ENVELOPE_BYTES = 2 * MAX_CONTEXT_BYTES
ROLES = ("source_files", "candidate_files", "oracle_files")


class SemanticFilePoolFailure(ValueError):
    """Sanitized rejection; decoding grants no authority, execution or success."""


class FileManifests(Contract):
    source_files: dict[str, Digest] = Field(max_length=MAX_FILES)
    candidate_files: dict[str, Digest] = Field(max_length=MAX_FILES)
    oracle_files: dict[str, Digest] = Field(max_length=MAX_FILES)


class SemanticFilePoolEnvelope(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["semantic-context-file-pool"] = "semantic-context-file-pool"
    profile: Literal["lossless-file-pool-v1"] = "lossless-file-pool-v1"
    original_context_digest: Digest
    context_without_file_maps: dict[str, Any]
    manifests: FileManifests
    blobs: dict[Digest, str] = Field(max_length=3 * MAX_FILES)


def _require(value: bool) -> None:
    if not value:
        raise SemanticFilePoolFailure("Semantic file-pool encoding is invalid or exceeds limits")


def _canonical(value: Any) -> bytes:
    # This is an explicit transport encoding, not the broker's HTTP wire format.
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False).encode("utf-8")


def _size(value: Any, limit: int) -> int:
    """Count bounded JSON without joining the whole serialized document."""
    # iterencode emits a complete escaped scalar at once. Bound every scalar and
    # the input tree first, so a malicious typed/model_copy input cannot make that
    # chunk unbounded. The byte-limited decoder has the same defensive check.
    pending = [iter((value,))]
    visited = 0
    while pending:
        try:
            current = next(pending[-1])
        except StopIteration:
            pending.pop()
            continue
        visited += 1
        _require(visited <= limit and len(pending) <= 32)
        if isinstance(current, str):
            _require(len(current) <= limit)
        elif isinstance(current, dict):
            pending.append(iter(chain(current.keys(), current.values())))
        elif isinstance(current, (list, tuple)):
            pending.append(iter(current))
    total = 0
    encoder = json.JSONEncoder(sort_keys=True, ensure_ascii=True, allow_nan=False)
    for chunk in encoder.iterencode(value):
        total += len(chunk)  # ensure_ascii=True makes characters equal UTF-8 bytes.
        _require(total <= limit)
    return total


def _content_hash(content: str) -> str:
    _require(isinstance(content, str) and len(content) <= MAX_FILE_BYTES)
    encoded = content.encode("utf-8")  # Invalid Unicode/surrogates cannot be a UTF-8 file.
    _require(len(encoded) <= MAX_FILE_BYTES)
    return hashlib.sha256(encoded).hexdigest()


def _checked_context(document: dict[str, Any]) -> SemanticScoringContext:
    _require(_size(document, MAX_CONTEXT_BYTES) <= MAX_CONTEXT_BYTES)
    context = SemanticScoringContext.model_validate(document)
    # Do not accept coercion, stripped strings, omitted defaults or extra metadata.
    _require(_canonical(context.model_dump(mode="json")) == _canonical(document))
    evidence = context.evidence
    _require(context.purpose == evidence.purpose)
    for role in ROLES:
        validate_files(getattr(evidence, role))
    _require(context.evidence_digest == digest_json(evidence.model_dump(mode="json")))
    _require(evidence.candidate_digest == digest_json(evidence.candidate_files))
    return context


def _pack(context: SemanticScoringContext) -> SemanticFilePoolEnvelope:
    document = context.model_dump(mode="json", warnings="error")
    checked = _checked_context(document)
    metadata = checked.model_dump(mode="json")
    manifests: dict[str, dict[str, str]] = {}
    blobs: dict[str, str] = {}
    for role in ROLES:
        files = metadata["evidence"].pop(role)
        manifest = {}
        for path, content in files.items():
            reference = _content_hash(content)
            _require(reference not in blobs or blobs[reference] == content)
            blobs[reference] = content
            manifest[path] = reference
        manifests[role] = manifest
    return SemanticFilePoolEnvelope(
        original_context_digest=digest_json(document),
        context_without_file_maps=metadata,
        manifests=FileManifests.model_validate(manifests),
        blobs=blobs,
    )


def encode_semantic_file_pool(context: SemanticScoringContext) -> bytes:
    """Preserve a typed context exactly; never authorize model use or authenticate artifacts."""
    try:
        _require(isinstance(context, SemanticScoringContext))
        envelope = _pack(context)
        document = envelope.model_dump(mode="json")
        _require(_size(document, MAX_ENVELOPE_BYTES) <= MAX_ENVELOPE_BYTES)
        return _canonical(document)
    except Exception:
        raise SemanticFilePoolFailure("Semantic context cannot be encoded losslessly") from None


def _pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in values:
        _require(key not in result)
        result[key] = value
    return result


def _nonfinite(_: str) -> None:
    raise SemanticFilePoolFailure("Nonfinite file-pool value")


def _expand(envelope: SemanticFilePoolEnvelope) -> dict[str, Any]:
    """Preflight expansion using lengths, before attaching repeated file-content values."""
    metadata = envelope.context_without_file_maps
    evidence = metadata.get("evidence")
    _require(isinstance(evidence, dict) and not set(ROLES) & evidence.keys())
    assert isinstance(evidence, dict)
    manifests = envelope.manifests.model_dump()
    used: set[str] = set()
    lengths: dict[str, int] = {}
    for reference, content in envelope.blobs.items():
        _require(reference == _content_hash(content))
        lengths[reference] = _size(content, MAX_CONTEXT_BYTES)
    # Empty maps account for all existing metadata/braces before adding individual entries.
    empty = {**metadata, "evidence": {**evidence, **{role: {} for role in ROLES}}}
    total = _size(empty, MAX_CONTEXT_BYTES)
    for role in ROLES:
        files = manifests[role]
        for path, reference in files.items():
            _require(safe_path(path) == path and reference in envelope.blobs)
            used.add(reference)
            total += _size(path, MAX_CONTEXT_BYTES) + 2 + lengths[reference]
            _require(total <= MAX_CONTEXT_BYTES)
        # Default JSON separators: ': ' between key/value and ', ' between entries.
        total += 2 * max(0, len(files) - 1)
        _require(total <= MAX_CONTEXT_BYTES)
    _require(used == set(envelope.blobs))
    # No content is repeated/serialized until the exact expanded-size check passes.
    return {
        **metadata,
        "evidence": {
            **evidence,
            **{
                role: {path: envelope.blobs[ref] for path, ref in manifests[role].items()}
                for role in ROLES
            },
        },
    }


def decode_semantic_file_pool(payload: bytes) -> SemanticScoringContext:
    """Decode canonical bounded bytes; the caller still needs current concrete authority."""
    try:
        _require(isinstance(payload, bytes) and 0 < len(payload) <= MAX_ENVELOPE_BYTES)
        document = json.loads(payload, object_pairs_hook=_pairs, parse_constant=_nonfinite)
        _require(isinstance(document, dict) and type(document.get("schema_version")) is int)
        envelope = SemanticFilePoolEnvelope.model_validate(document)
        _require(_canonical(envelope.model_dump(mode="json")) == payload)
        expanded = _expand(envelope)
        context = _checked_context(expanded)
        _require(digest_json(context.model_dump(mode="json")) == envelope.original_context_digest)
        # A second encoding must recover the exact envelope, including pool completeness.
        _require(_canonical(_pack(context).model_dump(mode="json")) == payload)
        return context
    except Exception:
        raise SemanticFilePoolFailure(
            "Semantic file-pool context cannot be reconstructed"
        ) from None
