"""Allowlisted observations from existing durable records, without payload reads."""

from typing import Annotated, Any, Literal

from pydantic import Field, model_validator
from sqlalchemy import Connection, func, select

from agentic_delivery.domain.models import Contract
from agentic_delivery.storage.schema import RunRecord, UsageRecord


class Observation(Contract):
    outcome: Literal["HTTP_RESPONSE", "TRANSPORT_ERROR", "CANCELLED"]
    http_status: Annotated[int, Field(strict=True, ge=100, le=599)] | None

    @model_validator(mode="after")
    def response_consistency(self) -> "Observation":
        if (self.outcome == "HTTP_RESPONSE") != (self.http_status is not None):
            raise ValueError("Operational response observation is inconsistent")
        return self


class Cleanup(Contract):
    status: Literal["CLEANED", "UNKNOWN"]
    verified_absent: Annotated[bool, Field(strict=True)]

    @model_validator(mode="after")
    def cleanup_consistency(self) -> "Cleanup":
        if (self.status == "CLEANED") != self.verified_absent:
            raise ValueError("Operational cleanup observation is inconsistent")
        return self


def json_type(connection: Connection, column: Any, *keys: str) -> Any:
    # SQLite JSON_EXTRACT exposes true/false as 1/0; retain the JSON type before
    # applying strict contracts. PostgreSQL keeps booleans through its JSON codec.
    if connection.dialect.name == "sqlite":
        return func.json_type(column, "$." + ".".join(keys))
    if connection.dialect.name == "postgresql":
        value = column
        for key in keys:
            value = value[key]
        return func.json_typeof(value)
    raise ValueError("Unsupported operational observation database")


def diagnostic_metrics(connection: Connection, identity: str, *, max_rows: int) -> dict[str, Any]:
    """Read fixed JSON scalars inside the caller's existing read-only snapshot."""
    observed = UsageRecord.result["provider_observation"]
    statement = (
        select(
            UsageRecord.id,
            observed["kind"].label("kind"),
            observed["schema_version"].label("schema_version"),
            observed["account_id"].label("account_id"),
            observed["operation_id"].label("operation_id"),
            observed["outcome"].label("outcome"),
            observed["http_status"].label("http_status"),
            json_type(
                connection, UsageRecord.result, "provider_observation", "schema_version"
            ).label("schema_type"),
        )
        .where(UsageRecord.workflow_id == identity)
        .order_by(UsageRecord.id)
        .limit(max_rows + 1)
    )
    records = list(connection.execute(statement).mappings())
    if len(records) > max_rows:
        raise ValueError("Operational observations exceed row limit")
    counts = {
        "recorded_observations": 0,
        "missing_observations": 0,
        "non_success_http_observations": 0,
        "transport_error_observations": 0,
        "cancelled_observations": 0,
    }
    for row in records:
        if all(row[key] is None for key in row if key != "id"):
            counts["missing_observations"] += 1
            continue
        if (
            row["kind"] != "model-provider-observation"
            or type(row["schema_version"]) is not int
            or row["schema_type"] not in {"integer", "number"}
            or row["schema_version"] != 1
            or row["account_id"] != identity
            or row["operation_id"] != row["id"]
        ):
            raise ValueError("Operational observation identity or schema is inconsistent")
        item = Observation.model_validate(
            {"outcome": row["outcome"], "http_status": row["http_status"]}
        )
        counts["recorded_observations"] += 1
        counts["non_success_http_observations"] += (
            item.outcome == "HTTP_RESPONSE" and item.http_status != 200
        )
        counts["transport_error_observations"] += item.outcome == "TRANSPORT_ERROR"
        counts["cancelled_observations"] += item.outcome == "CANCELLED"
    cleanup_record = (
        connection.execute(
            select(
                RunRecord.result["candidate_cleanup"]["status"].label("status"),
                RunRecord.result["candidate_cleanup"]["verified_absent"].label("verified_absent"),
                json_type(
                    connection, RunRecord.result, "candidate_cleanup", "verified_absent"
                ).label("verified_type"),
            ).where(RunRecord.id == identity)
        )
        .mappings()
        .one()
    )
    cleanup: dict[str, Any]
    if all(value is None for value in cleanup_record.values()):
        cleanup = {"status": "NOT_RECORDED", "verified_absent": None}
    else:
        verified = cleanup_record["verified_absent"]
        if connection.dialect.name == "sqlite" and cleanup_record["verified_type"] in {
            "true",
            "false",
        }:
            verified = cleanup_record["verified_type"] == "true"
        cleanup = Cleanup.model_validate(
            {"status": cleanup_record["status"], "verified_absent": verified}
        ).model_dump()
    return {
        "model_provider_observations": {
            **counts,
            "coverage_complete": counts["missing_observations"] == 0,
            "recorded_errors": counts["non_success_http_observations"]
            + counts["transport_error_observations"],
        },
        "candidate_cleanup_observation": cleanup,
    }
