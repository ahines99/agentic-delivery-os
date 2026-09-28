"""Honest synthetic imports cannot be reclassified as historical execution requests."""

from datetime import timedelta

import pytest
from test_synthetic_import import IMAGE, NOW, authored  # noqa: F401

from agentic_delivery.config import ModelConfig, RepositoryConfig, Settings
from agentic_delivery.evaluation import qualification_admission as admission
from agentic_delivery.evaluation.calibration import CalibrationPolicy
from agentic_delivery.evaluation.execution_store import EvaluationExecutionStore
from agentic_delivery.evaluation.qualification_preparation import PreparationPolicy
from agentic_delivery.evaluation.qualification_runtime import (
    DeterministicRequest,
    RuntimeAuthorization,
)
from agentic_delivery.evaluation.synthetic_import import import_synthetic_example
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json


@pytest.mark.parametrize("purpose", ["SYNTHETIC_VALIDATION", "HISTORICAL_QUALIFICATION"])
def test_purpose_is_bound_before_calibration_or_effects(
    authored,  # noqa: F811
    tmp_path,
    monkeypatch,
    purpose,
):
    examples, options = authored
    example, store = examples[0], options["artifacts"]
    imported = import_synthetic_example(example, **options)
    model = ModelConfig(
        model="controlled-test-model",
        input_microdollars_per_million=1,
        output_microdollars_per_million=1,
        rate_card_version="test-only",
    )
    settings = Settings(
        model=model,
        repositories=(
            RepositoryConfig(
                id="fixture/repo",
                github_owner="fixture",
                github_name="repo",
                sandbox_image=IMAGE,
                model_data_authorized=True,
                commands=(example.acceptance_command, example.regression_command),
            ),
        ),
    )
    policy = PreparationPolicy(
        schema_version=1,
        policy_version="mvp-1",
        authorized_issuers=("test-controller",),
        approved_authorization_artifacts=(imported.authorization_artifact,),
    )
    calibration = CalibrationPolicy(
        approved_spec_artifacts=("a" * 64,),
        approved_model_configurations=(digest_json(model.model_dump(mode="json")),),
        authorized_issuers=("test-controller",),
        maximum_budget=settings.budget,
    )
    document = store.put(b"Controlled preliminary fixture finding; no historical claim.")
    request = admission.QualificationRequestV2(
        schema_version=2,
        purpose=purpose,
        deterministic_request=DeterministicRequest(
            preparation=imported.preparation,
            behavior_nodes=example.behavior_nodes,
            regression_nodes=example.regression_nodes,
        ),
        rubric_artifact="b" * 64,
        calibration_spec_artifact="a" * 64,
        calibration_evidence_artifact="c" * 64,
        model_configuration=model,
        check_evidence={role: document for role in admission.ELIGIBILITY},
        findings=tuple(
            dict(
                check=role,
                status="PASS",
                summary="Controlled preliminary fixture finding",
                evidence_refs=(document,),
            )
            for role in admission.ELIGIBILITY
        ),
    )
    grant = admission.QualificationAuthorizationV2(
        schema_version=2,
        request_digest=digest_json(request.model_dump(mode="json")),
        runtime_authorization=RuntimeAuthorization(
            account_id="synthetic-purpose-boundary",
            request_digest=digest_json(request.deterministic_request.model_dump(mode="json")),
            execution_config_digest=settings.execution_digest("fixture/repo"),
            preparation_policy_digest=digest_json(policy.model_dump(mode="json")),
            budget=settings.budget,
            infrastructure_microdollars=100_000,
            total_microdollars=5_100_000,
            microdollars_per_second=1,
            rate_card_version="test-only",
            issued_at=NOW - timedelta(seconds=1),
            expires_at=NOW + timedelta(minutes=10),
        ),
        calibration_policy_digest=digest_json(calibration.model_dump(mode="json")),
        model_calls_authorized=True,
    )
    worker = tmp_path / "worker"
    worker.mkdir()
    ledger = EvaluationExecutionStore(f"sqlite+pysqlite:///{tmp_path / 'delivery_eval_purpose.db'}")
    reached = False

    def stop(*args, **kwargs):
        nonlocal reached
        reached = True
        raise ValueError("Stop at calibration boundary without execution")

    monkeypatch.setattr(admission, "validate_calibration", stop)
    try:
        with pytest.raises(admission.AdmissionFailure):
            admission.validate_execution_inputs(
                request,
                grant,
                settings=settings,
                preparation_policy=policy,
                calibration_policy=calibration,
                protected_artifacts=store,
                output_artifacts=ArtifactStore(tmp_path / "output"),
                worker_root=worker,
                ledger=ledger,
                now=NOW,
            )
        assert reached is (purpose == "SYNTHETIC_VALIDATION")
    finally:
        ledger.engine.dispose()
