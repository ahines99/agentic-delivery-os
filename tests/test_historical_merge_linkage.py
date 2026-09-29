"""Explicit merge metadata fixtures; no historical payload, transport or execution."""

import ast
import copy
import hashlib
import inspect
import json
from datetime import timedelta

import pytest
from test_historical_linkage import build_linkage_bundle

from agentic_delivery.evaluation import historical_linkage as linkage
from agentic_delivery.storage.store import digest_json

SECOND = "7" * 40


async def merge_bundle(tmp_path, **kwargs):
    response, options, derivation = await build_linkage_bundle(tmp_path, **kwargs)
    parents = response["data"]["repository"]["accepted"]["parents"]
    parents["totalCount"] = 2
    parents["nodes"].append({"oid": SECOND})
    return response, options, derivation


async def linked_merge(tmp_path, **kwargs):
    response, options, derivation = await merge_bundle(tmp_path, **kwargs)
    artifact = linkage.freeze_historical_merge_linkage(response, copy.deepcopy(response), **options)
    result = linkage.validate_historical_merge_linkage(
        artifact,
        protected_artifacts=options["protected_artifacts"],
        derivation=derivation,
        now=options["now"],
    )
    return (
        options["derivation_artifact"],
        derivation,
        artifact,
        result,
        options["protected_artifacts"],
        options["worker_roots"],
    )


def put(store, value):
    return store.put(json.dumps(value, sort_keys=True).encode())


def test_legacy_class_query_and_default_function_goldens():
    assert digest_json(linkage.HistoricalLinkageEvidence.model_json_schema()) == (
        "95315c53bb0ec191c05ad0ef5dd273a9cb87e28c5b4544676a8fe2581b263f66"
    )
    assert hashlib.sha256(linkage.LINKAGE_QUERY.encode()).hexdigest() == (
        "472c02fa566ba9a67481c2fd8798ed2fb32ccf778319921771608b28c66f8ad4"
    )
    # Frozen ASTs from700fc45; old public defaults and contracts are not reinterpreted.
    for value, expected in (
        (
            linkage.HistoricalLinkageEvidence,
            "b5ea19a03f2aa63ccd2a8451e7af8e49408f151bdcfcaabf48318452a3331a1c",
        ),
        (
            linkage.validate_historical_linkage,
            "8ef5536f8b9efc5510f76cbce63043956f5121e27725b7e2cf6da736ba8cda1e",
        ),
        (
            linkage.freeze_historical_linkage,
            "884e982b753593d66e5756e0b18a2b3cf5721a077bc0aff1e6f62549535285c4",
        ),
    ):
        tree = ast.parse(inspect.getsource(value)).body[0]
        # Python 3.13 omits empty lists by default; retain the original 3.12
        # representation so these goldens keep checking the same contracts.
        dump_options = (
            {"show_empty": True} if "show_empty" in inspect.signature(ast.dump).parameters else {}
        )
        assert (
            hashlib.sha256(
                ast.dump(tree, include_attributes=False, **dump_options).encode()
            ).hexdigest()
            == expected
        )


async def test_explicit_two_parent_readback_idempotence_and_legacy_denial(tmp_path, monkeypatch):
    response, options, derivation = await merge_bundle(tmp_path)
    store = options["protected_artifacts"]
    with pytest.raises(linkage.HistoricalLinkageFailure):
        linkage.freeze_historical_linkage(response, response, **options)
    ref = linkage.freeze_historical_merge_linkage(response, response, **options)
    read = dict(protected_artifacts=store, derivation=derivation, now=options["now"])
    result = linkage.validate_historical_linkage_record(ref, **read)
    assert isinstance(result, linkage.HistoricalMergeLinkageEvidenceV2)
    assert result.accepted_parents == (derivation.base_sha, SECOND)
    assert result.rights_cleared is result.admitted is result.cryptographic_authenticity is False
    assert linkage.freeze_historical_merge_linkage(response, response, **options) == ref
    with pytest.raises(linkage.HistoricalLinkageFailure):
        linkage.validate_historical_linkage(ref, **read)
    before = {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()}
    monkeypatch.setattr(store, "put", lambda *_: pytest.fail("Read-only validator wrote"))
    assert linkage.validate_historical_merge_linkage(ref, **read) == result
    assert before == {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()}


@pytest.mark.parametrize(
    "fault",
    [
        "reversed",
        "second_only_baseline",
        "duplicate",
        "self",
        "zero",
        "invalid_sha",
        "parent_extra_key",
        "single",
        "zero_count",
        "three",
        "truncated",
        "previous_page",
        "unknown_parent",
        "different_capture",
        "repo_id",
        "tree",
        "pr",
        "closer",
        "requirements_after_commit",
        "future_capture",
    ],
)
async def test_invalid_merge_metadata_refuses_without_partial_writes(tmp_path, fault):
    response, options, derivation = await merge_bundle(tmp_path)
    repo = response["data"]["repository"]
    parents = repo["accepted"]["parents"]
    second = response
    if fault == "reversed":
        parents["nodes"].reverse()
    elif fault == "second_only_baseline":
        parents["nodes"] = [{"oid": SECOND}, {"oid": derivation.base_sha}]
    elif fault in {"duplicate", "self", "zero", "invalid_sha"}:
        parents["nodes"][1]["oid"] = {
            "duplicate": derivation.base_sha,
            "self": derivation.accepted_commit,
            "zero": "0" * 40,
            "invalid_sha": "g" * 40,
        }[fault]
    elif fault == "parent_extra_key":
        parents["nodes"][1]["unknown"] = "not permitted"
    elif fault == "single":
        parents["nodes"].pop()
        parents["totalCount"] = 1
    elif fault == "zero_count":
        parents["totalCount"] = 0
    elif fault == "three":
        parents["nodes"].append({"oid": "8" * 40})
        parents["totalCount"] = 3
    elif fault in {"truncated", "previous_page"}:
        parents["pageInfo"]["hasNextPage" if fault == "truncated" else "hasPreviousPage"] = True
    elif fault == "unknown_parent":
        parents["nodes"][1] = None
    elif fault == "different_capture":
        second = copy.deepcopy(response)
        second["data"]["repository"]["accepted"]["parents"]["nodes"][1]["oid"] = "8" * 40
    elif fault == "repo_id":
        repo["databaseId"] += 1
    elif fault == "tree":
        repo["accepted"]["tree"]["oid"] = "8" * 40
    elif fault == "pr":
        repo["pullRequest"]["mergeCommit"]["oid"] = SECOND
    elif fault == "closer":
        repo["issue"]["timelineItems"]["nodes"][0]["closer"]["id"] = "another-pr"
    elif fault == "requirements_after_commit":
        repo["accepted"]["committedDate"] = "1999-01-01T00:00:00Z"
    else:
        options["captured_at"] = options["now"] + timedelta(seconds=1)
    store = options["protected_artifacts"]
    before = {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()}
    with pytest.raises(linkage.HistoricalLinkageFailure):
        linkage.freeze_historical_merge_linkage(response, second, **options)
    assert before == {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()}


@pytest.mark.parametrize(
    "fault",
    [
        "version",
        "kind",
        "bool",
        "missing_version",
        "missing_kind",
        "missing_profile",
        "profile",
        "parents",
        "base",
        "relabel_v1",
    ],
)
async def test_rehashed_record_or_unknown_dispatch_refuses(tmp_path, fault):
    _, derivation, ref, result, store, _ = await linked_merge(tmp_path)
    raw = result.model_dump(mode="json")
    if fault == "version":
        raw["schema_version"] = 3
    elif fault == "kind":
        raw["kind"] = "unknown"
    elif fault == "bool":
        raw["schema_version"] = True
    elif fault == "missing_version":
        del raw["schema_version"]
    elif fault == "missing_kind":
        del raw["kind"]
    elif fault == "missing_profile":
        del raw["parent_profile"]
    elif fault == "profile":
        raw["parent_profile"] = "ANY_PARENT_BASELINE"
    elif fault == "parents":
        raw["accepted_parents"].reverse()
    elif fault == "base":
        raw["base_sha"] = SECOND
    else:
        raw["schema_version"] = 1
        raw["kind"] = "provider-reported-merged-pr-linkage-v1"
        del raw["parent_profile"], raw["accepted_parents"]
    with pytest.raises(linkage.HistoricalLinkageFailure):
        linkage.validate_historical_linkage_record(
            put(store, raw), protected_artifacts=store, derivation=derivation
        )


async def test_v1_cannot_be_relabelled_as_merge_or_silently_upgraded(tmp_path):
    response, options, derivation = await build_linkage_bundle(tmp_path)
    store = options["protected_artifacts"]
    ref = linkage.freeze_historical_linkage(response, response, **options)
    read = dict(protected_artifacts=store, derivation=derivation, now=options["now"])
    old = linkage.validate_historical_linkage_record(ref, **read)
    assert isinstance(old, linkage.HistoricalLinkageEvidence)
    assert "accepted_parents" not in old.model_dump()
    with pytest.raises(linkage.HistoricalLinkageFailure):
        linkage.freeze_historical_merge_linkage(response, response, **options)
    raw = old.model_dump(mode="json")
    raw.update(
        schema_version=2,
        kind="provider-reported-first-parent-merge-linkage-v2",
        parent_profile="FIRST_PARENT_BASELINE_TWO_PARENTS",
        accepted_parents=[derivation.base_sha, SECOND],
    )
    with pytest.raises(linkage.HistoricalLinkageFailure):
        linkage.validate_historical_linkage_record(put(store, raw), **read)


async def test_current_import_consumes_exact_new_linkage_and_both_rights_pins(
    tmp_path, monkeypatch
):
    import test_historical_import_v2 as fixtures

    from agentic_delivery.evaluation.historical_import import import_historical_task_v2

    monkeypatch.setattr(fixtures, "linked_bundle", linked_merge)
    request, options, _, acquired = await fixtures.import_bundle(tmp_path)
    result = import_historical_task_v2(request, **options)
    assert result.status == "IMPORTED_NOT_QUALIFIED" and result.admitted is False
    assert acquired.linkage_artifact
    for missing in options["policy"].approved_authorization_artifacts:
        reduced = options["policy"].model_copy(
            update={
                "approved_authorization_artifacts": tuple(
                    ref
                    for ref in options["policy"].approved_authorization_artifacts
                    if ref != missing
                )
            }
        )
        with pytest.raises(ValueError):
            import_historical_task_v2(request, **{**options, "policy": reduced})


async def test_current_preparation_and_resolver_bind_merge_with_no_rights_bypass(
    tmp_path, monkeypatch
):
    import test_derived_qualification_input as fixtures

    from agentic_delivery.evaluation.qualification_input_resolution import (
        resolve_qualification_input,
    )
    from agentic_delivery.evaluation.qualification_preparation import prepare_qualification

    monkeypatch.setattr(fixtures, "linked_bundle", linked_merge)
    case = await fixtures.derived_case(tmp_path)
    result = prepare_qualification(case["request"], **case["args"])
    assert result.status == "PREPARED_NOT_QUALIFIED"
    wrapper = fixtures.wrapper_for(case)
    outer = put(case["store"], wrapper.model_dump(mode="json"))
    resolved = resolve_qualification_input(
        case["store"], outer, expected_preparation=case["request"]
    )
    assert case["reference"].linkage_artifact in resolved.forbidden_artifacts
    with pytest.raises(ValueError):
        prepare_qualification(
            case["request"], **{**case["args"], "now": case["args"]["now"] + timedelta(days=2)}
        )


async def test_cross_record_provider_evidence_and_derivation_are_not_interchangeable(tmp_path):
    _, derivation, ref, result, store, _ = await linked_merge(tmp_path / "merge")
    response, options, _ = await build_linkage_bundle(tmp_path / "single")
    oldref = linkage.freeze_historical_linkage(response, response, **options)
    other_store = options["protected_artifacts"]
    old = linkage.HistoricalLinkageEvidence.model_validate_json(other_store.get(oldref))
    alternate = store.put(other_store.get(old.provider_evidence_artifact))
    raw = result.model_dump(mode="json")
    raw["provider_evidence_artifact"] = alternate
    with pytest.raises(linkage.HistoricalLinkageFailure):
        linkage.validate_historical_linkage_record(
            put(store, raw), protected_artifacts=store, derivation=derivation
        )
    with pytest.raises(linkage.HistoricalLinkageFailure):
        linkage.validate_historical_linkage_record(
            ref,
            protected_artifacts=store,
            derivation=derivation.model_copy(update={"accepted_commit": SECOND}),
        )


async def test_new_linkage_and_sibling_alias_never_become_supporting_model_text(
    tmp_path, monkeypatch
):
    import test_derived_qualification_input as fixtures

    from agentic_delivery.evaluation.qualification_v2 import (
        _supporting_text,
        assemble_review_context,
    )

    monkeypatch.setattr(fixtures, "linked_bundle", linked_merge)
    case = await fixtures.derived_case(tmp_path)
    store = case["store"]
    wrapper = fixtures.wrapper_for(case)
    outer = put(store, wrapper.model_dump(mode="json"))
    rubric = store.put(b"Owned evidence completeness rubric.")
    with pytest.raises(ValueError):
        assemble_review_context(
            store,
            outer,
            rubric_artifact=case["reference"].linkage_artifact,
            stage="qualifier_a",
            context_id="owned-merge-review",
        )
    # A different artifact of this container kind is also forbidden, not merely
    # the exact digest in this wrapper's reconstructed exclusion closure.
    sibling = case["linkage"].model_dump(mode="json")
    sibling["pull_request_number"] += 1
    alias = put(store, sibling)
    with pytest.raises(ValueError):
        _supporting_text(store, alias, derived=True)
    altered = wrapper.model_dump(mode="json")
    altered["qualification_input"]["check_evidence"]["oracle"] = alias
    with pytest.raises(ValueError):
        assemble_review_context(
            store,
            put(store, altered),
            rubric_artifact=rubric,
            stage="qualifier_a",
            context_id="owned-merge-review",
        )
