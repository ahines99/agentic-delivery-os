"""Bound settled model-operation provenance; hashes do not authenticate arbitrary writers."""

from typing import Annotated, Any, Literal, Protocol, Self

from pydantic import AwareDatetime, Field, model_validator

from agentic_delivery.domain.models import Contract, NonEmpty
from agentic_delivery.storage.store import digest_json

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$", strict=True)]


class ModelUsageLedger(Protocol):
    """Delivery and evaluation keep separate accounts with identical reservation semantics."""

    def reserve(
        self,
        account_id: str,
        operation_id: str,
        cost: int,
        input_tokens: int,
        output_tokens: int,
        /,
    ) -> dict[str, Any] | None: ...

    def settle(
        self,
        operation_id: str,
        *,
        cost: int,
        input_tokens: int,
        output_tokens: int,
        result: dict[str, Any],
    ) -> None: ...

    def operation_receipt(self, account_id: str, operation_id: str) -> dict[str, Any]: ...

    def record_observation(
        self, account_id: str, operation_id: str, observation: dict[str, Any]
    ) -> None: ...


class ProviderObservation(Contract):
    """Allowlisted observed metadata; neither a parsed answer nor settlement authority."""

    schema_version: Literal[1] = 1
    kind: Literal["model-provider-observation"] = "model-provider-observation"
    account_id: NonEmpty
    operation_id: NonEmpty
    provider: Literal["openai", "anthropic"]
    request_digest: Digest
    configuration_digest: Digest
    started_at: AwareDatetime
    observed_at: AwareDatetime
    outcome: Literal["HTTP_RESPONSE", "TRANSPORT_ERROR", "CANCELLED"]
    http_status: int | None = Field(default=None, strict=True, ge=100, le=599)
    response_digest: Digest | None = None
    provider_response_id: NonEmpty | None = Field(default=None, max_length=256)
    returned_model: NonEmpty | None = Field(default=None, max_length=256)
    termination: (
        Literal[
            "end_turn",
            "max_tokens",
            "stop_sequence",
            "tool_use",
            "pause_turn",
            "refusal",
            "model_context_window_exceeded",
            "completed",
            "failed",
            "in_progress",
            "incomplete",
            "cancelled",
            "queued",
            "OTHER",
        ]
        | None
    ) = None
    reported_input_tokens: int | None = Field(default=None, strict=True, ge=0, le=2**63 - 1)
    reported_output_tokens: int | None = Field(default=None, strict=True, ge=0, le=2**63 - 1)

    @model_validator(mode="after")
    def response_fields(self) -> Self:
        observed = self.model_dump()
        optional = (
            "http_status",
            "response_digest",
            "provider_response_id",
            "returned_model",
            "termination",
            "reported_input_tokens",
            "reported_output_tokens",
        )
        if self.outcome == "HTTP_RESPONSE":
            if self.http_status is None or self.response_digest is None:
                raise ValueError("HTTP observation needs status and response digest")
        elif any(observed[name] is not None for name in optional):
            raise ValueError("Unobserved response metadata must remain absent")
        return self


class ModelOperationReceipt(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["settled-model-operation"] = "settled-model-operation"
    account_id: NonEmpty
    operation_id: NonEmpty
    provider: Literal["openai", "anthropic"]
    provider_response_id: NonEmpty = Field(max_length=256)
    requested_model: NonEmpty = Field(max_length=256)
    returned_model: NonEmpty = Field(max_length=256)
    request_digest: Digest
    prompt_digest: Digest
    context_digest: Digest
    schema_digest: Digest
    configuration_digest: Digest
    output_digest: Digest
    started_at: AwareDatetime
    completed_at: AwareDatetime
    input_tokens: int = Field(strict=True, ge=0)
    output_tokens: int = Field(strict=True, ge=0)
    cost_microdollars: int = Field(strict=True, ge=0)
    input_microdollars_per_million: int = Field(strict=True, gt=0)
    output_microdollars_per_million: int = Field(strict=True, gt=0)
    rate_card_version: NonEmpty

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.completed_at < self.started_at:
            raise ValueError("Model receipt completion precedes request start")
        calculated = (
            self.input_tokens * self.input_microdollars_per_million
            + self.output_tokens * self.output_microdollars_per_million
            + 999_999
        ) // 1_000_000
        if calculated != self.cost_microdollars:
            raise ValueError("Model receipt cost does not match its token counts and rate card")
        return self


def receipt_from_result(result: dict[str, Any]) -> ModelOperationReceipt:
    """Validate a trusted ledger's settled payload; absent legacy provenance is not invented."""
    if not isinstance(result, dict):
        raise ValueError("Model operation result must be a structured object")
    receipt = ModelOperationReceipt.model_validate(result.get("operation_receipt"))
    if (
        receipt.output_digest != digest_json(result["output"])
        or receipt.provider_response_id != result.get("provider_id")
        or receipt.returned_model != result.get("model")
        or receipt.rate_card_version != result.get("rate_card_version")
    ):
        raise ValueError("Model receipt does not bind the settled output")
    return receipt


def validate_operation_receipt(
    operation: dict[str, Any], *, account_id: str, operation_id: str
) -> ModelOperationReceipt:
    """Check result provenance against its owning ledger record and conservative reservation."""
    if (
        operation.get("account_id") != account_id
        or operation.get("operation_id") != operation_id
        or operation.get("status") != "SETTLED"
    ):
        raise ValueError("Model operation is not settled for the requested account")
    receipt = receipt_from_result(operation["result"])
    for name in (
        "actual_microdollars",
        "actual_input_tokens",
        "actual_output_tokens",
        "reserved_microdollars",
        "reserved_input_tokens",
        "reserved_output_tokens",
    ):
        if type(operation.get(name)) is not int or operation[name] < 0:
            raise ValueError("Model ledger accounting must contain nonnegative integer values")
    if (
        receipt.account_id != account_id
        or receipt.operation_id != operation_id
        or receipt.cost_microdollars != operation.get("actual_microdollars")
        or receipt.input_tokens != operation.get("actual_input_tokens")
        or receipt.output_tokens != operation.get("actual_output_tokens")
        or receipt.cost_microdollars > operation["reserved_microdollars"]
        or receipt.input_tokens > operation["reserved_input_tokens"]
        or receipt.output_tokens > operation["reserved_output_tokens"]
    ):
        raise ValueError("Model receipt conflicts with ledger accounting")
    if "provider_observation" in operation["result"]:
        observation_document = operation["result"]["provider_observation"]
        observation = ProviderObservation.model_validate(observation_document)
        if (
            observation.outcome != "HTTP_RESPONSE"
            or observation.http_status != 200
            or observation.account_id != receipt.account_id
            or observation.operation_id != receipt.operation_id
            or observation.provider != receipt.provider
            or observation.request_digest != receipt.request_digest
            or observation.configuration_digest != receipt.configuration_digest
            or observation.provider_response_id != receipt.provider_response_id
            or observation.returned_model != receipt.returned_model
            or observation.reported_input_tokens != receipt.input_tokens
            or observation.reported_output_tokens != receipt.output_tokens
            or observation.started_at != receipt.started_at
            or operation.get("observation", observation_document) != observation_document
            or not receipt.started_at <= observation.observed_at <= receipt.completed_at
            or observation.termination
            != ("end_turn" if receipt.provider == "anthropic" else "completed")
        ):
            raise ValueError("Model receipt conflicts with observed provider metadata")
    return receipt
