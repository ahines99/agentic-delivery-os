"""Authenticated intake; commands are queued, never executed in HTTP handlers."""

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from agentic_delivery import __version__
from agentic_delivery.agents.manual_acceptance import manual_readiness, validate_manual_decision
from agentic_delivery.config import Operator, Settings, load_settings, secret
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.integrations.checks import parse_check_run
from agentic_delivery.security import AccessDenied, authenticate, authorize, verified_payload
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.schema import RunRecord
from agentic_delivery.storage.store import Conflict, NotFound, Store


def create_app(settings: Settings | None = None, store: Store | None = None) -> FastAPI:
    settings = settings or load_settings()
    store = store or Store(create_database(settings.database_url))
    api = FastAPI(title="Agentic Delivery OS", version=__version__)
    api.state.settings, api.state.store = settings, store

    @api.exception_handler(AccessDenied)
    async def denied(_: Request, exc: AccessDenied) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=403)

    @api.exception_handler(Conflict)
    async def conflict(_: Request, exc: Conflict) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @api.exception_handler(NotFound)
    async def not_found(_: Request, exc: NotFound) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @api.exception_handler(ValidationError)
    async def invalid(_: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(
            {
                "detail": "Invalid request schema",
                "fields": [error["loc"] for error in exc.errors()],
            },
            status_code=422,
        )

    @api.exception_handler(ValueError)
    async def bad_value(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=422)

    async def body(request: Request) -> bytes:
        chunks = bytearray()
        async for chunk in request.stream():
            chunks.extend(chunk)
            if len(chunks) > settings.max_body_bytes:
                raise AccessDenied("Request body too large")
        return bytes(chunks)

    def operator(request: Request) -> Operator:
        return authenticate(settings, request.headers.get("authorization"))

    def key(request: Request) -> str:
        value = request.headers.get("idempotency-key", "")
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", value):
            raise ValueError("A valid Idempotency-Key header is required")
        return value

    def permitted_run(request: Request, identity: str, role: str = "reader") -> dict[str, Any]:
        actor = operator(request)
        run = store.workflow(identity)
        authorize(actor, run["repository"], role)
        return run

    @api.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__, "mode": "durable-control-plane"}

    @api.get("/work-items")
    def list_items(request: Request) -> list[dict[str, Any]]:
        return store.list_workflows(operator(request).repositories)

    @api.get("/readyz")
    def ready() -> JSONResponse:
        try:
            with store.engine.connect() as connection:
                connection.execute(select(RunRecord.configuration_digest).limit(1))
        except SQLAlchemyError:
            return JSONResponse({"status": "unavailable", "database": "not_ready"}, status_code=503)
        return JSONResponse({"status": "ready", "database": "ready"})

    @api.get("/operations")
    def operations(request: Request) -> dict[str, Any]:
        actor = operator(request)
        return store.operational_summary(actor.repositories)

    @api.post("/work-items", status_code=202)
    async def submit(request: Request) -> dict[str, Any]:
        actor = operator(request)
        if not settings.admissions_enabled:
            raise AccessDenied("New admission is paused")
        item = WorkItem.model_validate_json(await body(request))
        repository = settings.repository(item.repository)
        authorize(actor, item.repository, "operator")
        if item.base_branch != repository.base_branch or item.source_system != "local":
            raise AccessDenied("Input source or branch not authorized")
        return store.submit(
            item,
            actor=actor.id,
            key=key(request),
            budget=settings.budget,
            configuration_digest=settings.execution_digest(item.repository),
        )

    @api.get("/workflows/{identity}")
    def get_run(identity: str, request: Request) -> dict[str, Any]:
        return permitted_run(request, identity)

    @api.get("/workflows/{identity}/events")
    def events(identity: str, request: Request, after: int = 0) -> list[dict[str, Any]]:
        permitted_run(request, identity)
        return store.events(identity, max(0, after))

    @api.get("/workflows/{identity}/manual-review")
    def manual_review(identity: str, request: Request) -> dict[str, Any]:
        permitted_run(request, identity)
        return manual_readiness(settings, store, identity)

    @api.get("/commands/{identity}")
    def command(identity: str, request: Request) -> dict[str, Any]:
        operator(request)
        result = store.command(identity)
        permitted_run(request, result["workflow_id"])
        return result

    @api.post("/workflows/{identity}/{operation}", status_code=202)
    async def send_command(identity: str, operation: str, request: Request) -> dict[str, Any]:
        run = permitted_run(request, identity, "operator")
        if operation not in {"cancel", "clarify", "approve-plan", "manual-review", "rerun"}:
            raise NotFound("Command does not exist")
        payload = json.loads(await body(request))
        if not isinstance(payload, dict):
            raise ValueError("Command must be a JSON object")
        if operation == "manual-review":
            actor = operator(request)
            decision = validate_manual_decision(
                settings, store, identity, payload, actor_id=actor.id
            )
            return store.enqueue_command(
                identity,
                kind=operation,
                payload=decision.model_dump(mode="json"),
                actor=actor.id,
                key=key(request),
            )
        allowed = {"expected_sequence", "spec_digest"}
        if operation == "clarify":
            allowed.add("item")
            item = WorkItem.model_validate(payload.get("item"))
            original = WorkItem.model_validate(run["work_item"])
            if any(
                getattr(item, field) != getattr(original, field)
                for field in ("id", "source_system", "repository", "base_branch")
            ):
                raise AccessDenied("Clarification cannot change source or repository identity")
        if operation == "approve-plan":
            authorize(operator(request), run["repository"], "reviewer")
            allowed.add("plan_digest")
            if not re.fullmatch(r"[a-f0-9]{64}", str(payload.get("plan_digest", ""))):
                raise ValueError("Plan digest is required")
        if set(payload) != allowed or type(payload.get("expected_sequence")) is not int:
            raise ValueError("Command has missing or unknown fields")
        if not re.fullmatch(r"[a-f0-9]{64}", str(payload.get("spec_digest", ""))):
            raise ValueError("Specification digest is required")
        if operation == "rerun":
            if not settings.admissions_enabled:
                raise AccessDenied("New admission is paused")
            return store.rerun(
                identity,
                actor=operator(request).id,
                key=key(request),
                budget=settings.budget,
                configuration_digest=settings.execution_digest(run["repository"]),
                **payload,
            )
        return store.enqueue_command(
            identity, kind=operation, payload=payload, actor=operator(request).id, key=key(request)
        )

    @api.post("/webhooks/linear")
    async def linear(request: Request) -> dict[str, Any]:
        if not settings.admissions_enabled or not settings.linear_organization_id:
            raise AccessDenied("Linear intake is not enabled")
        raw = await body(request)
        payload = verified_payload(
            raw,
            request.headers.get("linear-signature"),
            secret(settings.linear_webhook_secret_env),
            provider="linear",
            max_bytes=settings.max_body_bytes,
        )
        if payload.get("organizationId") != settings.linear_organization_id:
            raise AccessDenied("Linear organization not authorized")
        if payload.get("type") != "Issue" or payload.get("action") not in {"create", "update"}:
            return {"status": "ignored", "reason": "Unsupported event"}
        data = payload.get("data", {})
        repository = next(
            (
                r
                for r in settings.repositories
                if r.linear_team_id == data.get("teamId") and r.linear_team_id
            ),
            None,
        )
        if not repository or not repository.linear_assignee_id:
            raise AccessDenied("Linear team or worker mapping not configured")
        if data.get("assigneeId") != repository.linear_assignee_id:
            return {"status": "ignored", "reason": "Not assigned to this worker"}
        delivery = request.headers.get("linear-delivery", "")
        if not re.fullmatch(r"[A-Za-z0-9-]{1,200}", delivery):
            raise ValueError("Linear delivery identifier is missing or invalid")
        item = WorkItem(
            id=data["id"],
            source_system="linear",
            title=data["title"],
            description=data.get("description") or data["title"],
            repository=repository.id,
            base_branch=repository.base_branch,
        )
        updated = data.get("updatedAt") or payload.get("createdAt")
        if not isinstance(updated, str) or not updated:
            raise ValueError("Signed event resource version missing")
        inbox = {
            "provider": "linear",
            "integration_id": settings.linear_organization_id,
            "delivery_id": delivery,
            "semantic_key": f"Issue:{item.id}:{updated}",
            "digest": hashlib.sha256(raw).hexdigest(),
            "payload": payload,
        }
        return store.submit(
            item,
            actor="linear-webhook",
            key=f"linear:{delivery}",
            budget=settings.budget,
            inbox=inbox,
            configuration_digest=settings.execution_digest(item.repository),
        )

    @api.get("/workflows/{identity}/publication")
    def publication(identity: str, request: Request) -> dict[str, Any]:
        permitted_run(request, identity)
        return store.publication(identity)

    @api.get("/workflows/{identity}/checks")
    def checks(identity: str, request: Request) -> dict[str, Any]:
        run = permitted_run(request, identity)
        repository = settings.repository(run["repository"])
        unavailable = {
            "ready": False,
            "ci_ready": False,
            "observed_ready": False,
            "reconciliation_required": True,
            "observational_only": True,
            "selected_run_ids": {},
        }
        if repository.github_repository_id is None:
            return {**unavailable, "reasons": ["github_repository_identity_not_configured"]}
        try:
            published = store.publication(identity)
        except NotFound:
            return {**unavailable, "reasons": ["publication_missing"]}
        result = store.ci_readiness(
            repository_id=repository.github_repository_id,
            head_sha=published["head_sha"],
            required=repository.required_checks,
            policy_digest=settings.execution_digest(repository.id),
        )
        result["ci_ready"] = result["ready"]
        if published["status"] != "DRAFT_HANDOFF" or any(
            (
                published.get("repository_id") != repository.github_repository_id,
                published.get("repository_full_name")
                != f"{repository.github_owner}/{repository.github_name}",
                published.get("head_ref") != "agent/" + identity,
                published.get("base_ref") != repository.base_branch,
            )
        ):
            result["ready"] = False
            result["observed_ready"] = False
            result["reconciliation_required"] = True
            result["reasons"] = [*result["reasons"], "publication_not_current"]
            result["ci_ready"] = False
        if run["state"] != "HUMAN_REVIEW":
            result["ready"] = False
            result["reasons"] = [*result["reasons"], "workflow_not_human_review"]
        if result["ready"]:
            try:
                expected = settings.execution_digest(repository.id)
                if run["configuration_digest"] != expected:
                    raise ValueError("Configuration changed")
                artifacts = ArtifactStore(settings.artifact_root)
                manifest = json.loads(artifacts.get(published["manifest_digest"]))
                if any(
                    (
                        manifest.get("workflow_id") != identity,
                        manifest.get("repository") != repository.id,
                        manifest.get("base_sha") != published["base_sha"],
                        manifest.get("input_spec_digest") != run["spec_digest"],
                        manifest.get("configuration_digest") != expected,
                    )
                ):
                    raise ValueError("Manifest context changed")
                approval = store.approved_plan(identity, manifest["approved_plan_digest"])
                approved_at = datetime.fromisoformat(approval["created_at"])
                actor = next((op for op in settings.operators if op.id == approval["actor"]), None)
                if (
                    actor is None
                    or approved_at.tzinfo is None
                    or datetime.now(UTC)
                    >= approved_at + timedelta(seconds=settings.approval_validity_seconds)
                    or approval["payload"].get("spec_digest") != run["spec_digest"]
                ):
                    raise ValueError("Approval is no longer current")
                authorize(actor, repository.id, "reviewer")
                ci_evidence = json.loads(artifacts.get(result["evidence_digest"]))
                context = ci_evidence.get("publication", {})
                if (
                    ci_evidence.get("workflow_id") != identity
                    or ci_evidence.get("configuration_digest") != expected
                    or any(
                        context.get(field) != published[field]
                        for field in ("number", "head_sha", "base_sha", "manifest_digest")
                    )
                ):
                    raise ValueError("CI evidence publication context changed")
            except (ValueError, KeyError, TypeError, OSError):
                result["ready"] = False
                result["reasons"] = [*result["reasons"], "handoff_authority_not_current"]
        return {**result, "observational_only": True}

    @api.post("/webhooks/github")
    async def github(request: Request) -> dict[str, Any]:
        if not settings.github_installation_id:
            raise AccessDenied("GitHub webhook is not configured")
        raw = await body(request)
        payload = verified_payload(
            raw,
            request.headers.get("x-hub-signature-256"),
            secret(settings.github_webhook_secret_env),
            provider="github",
            max_bytes=settings.max_body_bytes,
        )
        installation = payload.get("installation")
        if (
            not isinstance(installation, dict)
            or type(installation.get("id")) is not int
            or installation["id"] != settings.github_installation_id
        ):
            raise AccessDenied("Installation not authorized")
        provider_repository = payload.get("repository") or {}
        if (
            not isinstance(provider_repository, dict)
            or type(provider_repository.get("id")) is not int
        ):
            raise AccessDenied("Repository identity missing or invalid")
        repository = next(
            (
                repo
                for repo in settings.repositories
                if repo.github_repository_id is not None
                and repo.github_repository_id == provider_repository.get("id")
                and provider_repository.get("full_name")
                == f"{repo.github_owner}/{repo.github_name}"
            ),
            None,
        )
        if repository is None:
            raise AccessDenied("Repository not authorized")
        if "check_run" in payload:
            if "pull_request" in payload or "check_suite" in payload:
                raise ValueError("Ambiguous GitHub event payload")
            assert repository.github_repository_id is not None
            observation = parse_check_run(
                payload,
                repository_id=repository.github_repository_id,
                installation_id=settings.github_installation_id,
            )
            delivery = request.headers.get("x-github-delivery", "")
            if not re.fullmatch(r"[A-Za-z0-9-]{1,200}", delivery):
                raise ValueError("Delivery identifier missing or invalid")
            digest = hashlib.sha256(raw).hexdigest()
            return store.record_check_observation(
                observation,
                {
                    "provider": "github",
                    "integration_id": str(settings.github_installation_id),
                    "delivery_id": delivery,
                    "semantic_key": digest,
                    "digest": digest,
                    "payload": payload,
                },
            )
        if "check_suite" in payload:
            if "pull_request" in payload:
                raise ValueError("Ambiguous GitHub event payload")
            assert repository.github_repository_id is not None
            delivery = request.headers.get("x-github-delivery", "")
            if not re.fullmatch(r"[A-Za-z0-9-]{1,200}", delivery):
                raise ValueError("Delivery identifier missing or invalid")
            digest = hashlib.sha256(raw).hexdigest()
            return store.record_check_suite_invalidation(
                payload,
                {
                    "provider": "github",
                    "integration_id": str(settings.github_installation_id),
                    "delivery_id": delivery,
                    "semantic_key": digest,
                    "digest": digest,
                    "payload": payload,
                },
                repository_id=repository.github_repository_id,
            )
        pull = payload.get("pull_request")
        if not isinstance(pull, dict):
            return {"status": "ignored", "reason": "Not a pull request notification"}
        number = pull.get("number")
        if not isinstance(number, int) or isinstance(number, bool):
            raise ValueError("Pull request number is missing or invalid")
        identity = store.workflow_for_publication(repository.id, number)
        if identity is None:
            head = pull.get("head")
            branch = head.get("ref", "") if isinstance(head, dict) else ""
            if not isinstance(branch, str) or not re.fullmatch(r"agent/[a-zA-Z0-9-]{1,80}", branch):
                return {"status": "ignored", "reason": "Unmanaged branch"}
            identity = branch.removeprefix("agent/")
        run = store.workflow(identity)
        if run["repository"] != repository.id:
            raise AccessDenied("Workflow repository mismatch")
        delivery = request.headers.get("x-github-delivery", "")
        if not re.fullmatch(r"[A-Za-z0-9-]{1,200}", delivery):
            raise ValueError("Delivery identifier missing or invalid")
        digest = hashlib.sha256(raw).hexdigest()
        inbox = {
            "provider": "github",
            "integration_id": str(settings.github_installation_id),
            "delivery_id": delivery,
            "semantic_key": digest,
            "digest": digest,
            "payload": payload,
        }
        return store.observe_publication(identity, payload, inbox)

    return api


app = create_app()
