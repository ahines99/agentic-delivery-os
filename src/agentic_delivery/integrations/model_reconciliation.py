"""Trusted, network-free accounting of one narrowly evidenced failed model call."""

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, Field, TypeAdapter

from agentic_delivery.config import ModelConfig
from agentic_delivery.domain.models import Contract, NonEmpty
from agentic_delivery.evaluation.execution_store import EvaluationExecutionStore
from agentic_delivery.integrations.model import forecast_request
from agentic_delivery.integrations.model_receipts import Digest, ProviderObservation
from agentic_delivery.storage.store import digest_json

MAX_INTEGER = 2**63 - 1


class ReconciliationFailure(ValueError):
    """The evidence cannot authorize financial settlement; no payload is disclosed."""


class FinancialFailureReceipt(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["financial-model-failure"] = "financial-model-failure"
    outcome: Literal["MAX_TOKENS_FAILURE"] = "MAX_TOKENS_FAILURE"
    execution_succeeded: Literal[False] = False
    retry_authorized: Literal[False] = False
    account_id: NonEmpty
    operation_id: NonEmpty
    provider: Literal["anthropic"] = "anthropic"
    requested_model: NonEmpty
    returned_model: NonEmpty
    provider_response_id: NonEmpty
    response_digest: Digest
    observation_digest: Digest
    request_digest: Digest
    prompt_digest: Digest
    context_digest: Digest
    schema_digest: Digest
    configuration_digest: Digest
    started_at: AwareDatetime
    observed_at: AwareDatetime
    input_tokens: int = Field(strict=True, gt=0, le=MAX_INTEGER)
    output_tokens: int = Field(strict=True, gt=0, le=MAX_INTEGER)
    cost_microdollars: int = Field(strict=True, gt=0, le=MAX_INTEGER)
    input_microdollars_per_million: int = Field(strict=True, gt=0, le=MAX_INTEGER)
    output_microdollars_per_million: int = Field(strict=True, gt=0, le=MAX_INTEGER)
    rate_card_version: NonEmpty


def _require(value: bool) -> None:
    if not value:
        raise ReconciliationFailure("Failed-call financial evidence is absent or inconsistent")


def reconcile_max_tokens_failure(
    ledger: EvaluationExecutionStore,
    *,
    account_id: str,
    operation_id: str,
    config: ModelConfig,
    instructions: str,
    context: dict[str, Any],
    output_type: type[BaseModel],
    expected_observation_digest: str,
    now: datetime | None = None,
) -> FinancialFailureReceipt:
    """Settle known configured-rate usage, never create output or permission to retry.

    The caller is a trusted local accounting controller with the original request
    and independently selected observation digest. Hashes are not authentication.
    No grant renewal, provider request, key lookup or reservation is performed.
    """
    try:
        _require(isinstance(ledger, EvaluationExecutionStore))
        config = ModelConfig.model_validate(config.model_dump(mode="json"))
        observed_digest = TypeAdapter(Digest).validate_python(expected_observation_digest)
        forecast = forecast_request(
            config, instructions=instructions, context=context, output_type=output_type
        )
        operation = ledger.operation_receipt(account_id, operation_id)
        # Sample after the read: an identical concurrent caller may have committed
        # while this caller waited on the database connection/row.
        current_time = TypeAdapter(AwareDatetime).validate_python(now or datetime.now(UTC))
        _require(
            operation["account_id"] == account_id
            and operation["operation_id"] == operation_id
            and operation["status"] in {"RESERVED", "SETTLED"}
            and config.provider == forecast.provider == "anthropic"
        )
        result = operation["result"]
        _require(isinstance(result, dict))
        raw = result["provider_observation"]
        observation = ProviderObservation.model_validate(raw)
        created_at = TypeAdapter(AwareDatetime).validate_python(operation["created_at"])
        _require(
            raw == observation.model_dump(mode="json")
            and operation["observation"] == raw
            and digest_json(raw) == observed_digest
            and observation.account_id == account_id
            and observation.operation_id == operation_id
            and observation.provider == "anthropic"
            and observation.outcome == "HTTP_RESPONSE"
            and observation.http_status == 200
            and observation.termination == "max_tokens"
            and observation.returned_model == config.model
            and observation.request_digest == forecast.request_digest
            and observation.configuration_digest == forecast.configuration_digest
            and created_at <= observation.started_at <= observation.observed_at <= current_time
            and observation.provider_response_id is not None
            and observation.response_digest is not None
        )
        for key, expected in (
            ("reserved_microdollars", forecast.reservation_microdollars),
            ("reserved_input_tokens", forecast.upper_input_tokens),
            ("reserved_output_tokens", forecast.max_output_tokens),
        ):
            _require(type(operation[key]) is int and 0 < operation[key] == expected <= MAX_INTEGER)
        incoming, outgoing = observation.reported_input_tokens, observation.reported_output_tokens
        _require(type(incoming) is int and type(outgoing) is int)
        assert incoming is not None and outgoing is not None
        _require(
            0 < incoming <= forecast.upper_input_tokens and outgoing == config.max_output_tokens
        )
        cost = (
            incoming * config.input_microdollars_per_million
            + outgoing * config.output_microdollars_per_million
            + 999_999
        ) // 1_000_000
        _require(0 < cost <= forecast.reservation_microdollars)
        receipt = FinancialFailureReceipt(
            account_id=account_id,
            operation_id=operation_id,
            requested_model=config.model,
            returned_model=observation.returned_model,
            provider_response_id=observation.provider_response_id,
            response_digest=observation.response_digest,
            observation_digest=observed_digest,
            request_digest=forecast.request_digest,
            prompt_digest=forecast.prompt_digest,
            context_digest=forecast.context_digest,
            schema_digest=forecast.schema_digest,
            configuration_digest=forecast.configuration_digest,
            started_at=observation.started_at,
            observed_at=observation.observed_at,
            input_tokens=incoming,
            output_tokens=outgoing,
            cost_microdollars=cost,
            input_microdollars_per_million=config.input_microdollars_per_million,
            output_microdollars_per_million=config.output_microdollars_per_million,
            rate_card_version=config.rate_card_version,
        )
        financial = {"financial_failure_receipt": receipt.model_dump(mode="json")}
        expected_result = {**financial, "provider_observation": raw}
        if operation["status"] == "RESERVED":
            _require(set(result) == {"provider_observation"})
            _require(
                all(
                    operation[key] is None
                    for key in (
                        "actual_microdollars",
                        "actual_input_tokens",
                        "actual_output_tokens",
                    )
                )
            )
        else:
            _require(result == expected_result)
            settled_at = TypeAdapter(AwareDatetime).validate_python(operation["settled_at"])
            _require(observation.observed_at <= settled_at <= current_time)
        # Explicit observation prevents a missing/different capture being silently
        # merged during a race. Ledger settlement serializes and refuses conflicts.
        ledger.settle(
            operation_id,
            cost=cost,
            input_tokens=incoming,
            output_tokens=outgoing,
            result=expected_result,
        )
        settled = ledger.operation_receipt(account_id, operation_id)
        _require(
            settled["status"] == "SETTLED"
            and settled["result"] == expected_result
            and settled["observation"] == raw
            and settled["actual_microdollars"] == cost
            and settled["actual_input_tokens"] == incoming
            and settled["actual_output_tokens"] == outgoing
        )
        return receipt
    except Exception:
        raise ReconciliationFailure("Failed-call financial reconciliation was refused") from None
