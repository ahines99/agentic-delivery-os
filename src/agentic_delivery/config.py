"""Versioned private operator configuration; provider secrets use environment references."""

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from agentic_delivery.domain.models import Contract, NonEmpty


class Budget(Contract):
    model_microdollars: int = Field(default=5_000_000, gt=0, strict=True)
    input_tokens: int = Field(default=100_000, gt=0, strict=True)
    output_tokens: int = Field(default=20_000, gt=0, strict=True)
    wall_seconds: int = Field(default=1800, gt=0, le=7200, strict=True)
    command_seconds: int = Field(default=600, gt=0, le=1800, strict=True)
    repair_rounds: int = Field(default=2, ge=0, le=5, strict=True)


class Operator(Contract):
    id: NonEmpty
    token_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    repositories: tuple[NonEmpty, ...]
    roles: tuple[Literal["reader", "operator", "reviewer"], ...] = ("reader",)


class CommandProfile(Contract):
    id: NonEmpty
    argv: tuple[NonEmpty, ...] = Field(min_length=1)
    expected_tests: int = Field(default=1, ge=1, strict=True)


class RepositoryConfig(Contract):
    id: NonEmpty
    github_owner: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")
    github_name: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,100}$")
    base_branch: NonEmpty = "main"
    linear_team_id: NonEmpty | None = None
    linear_assignee_id: NonEmpty | None = None
    linear_review_state_id: NonEmpty | None = None
    github_repository_id: int | None = Field(default=None, gt=0, strict=True)
    commands: tuple[CommandProfile, ...] = ()
    protected_paths: tuple[str, ...] = (
        ".github/",
        "AGENTS.md",
        "CODEOWNERS",
        "Dockerfile",
        "infra/",
        ".env",
    )
    model_data_authorized: bool = False
    snapshot_prefix: str = ""
    sandbox_image: str | None = None
    local_repository: Path | None = None

    @model_validator(mode="after")
    def validate_refs(self) -> Self:
        if self.snapshot_prefix:
            from agentic_delivery.execution.files import safe_path

            safe_path(self.snapshot_prefix)
        if (
            self.github_name in {".", ".."}
            or self.base_branch.startswith(("-", "/"))
            or re.search(r"[\s~^:?*\[\\]", self.base_branch)
            or any(part in self.base_branch for part in ("..", "@{", "//"))
            or self.base_branch.endswith(("/", ".", ".lock"))
        ):
            raise ValueError("Invalid repository name or branch")
        return self


class ModelConfig(Contract):
    provider: Literal["openai", "anthropic"] = "openai"
    model: NonEmpty
    api_key_env: str = "OPENAI_API_KEY"
    input_microdollars_per_million: int = Field(gt=0, strict=True)
    output_microdollars_per_million: int = Field(gt=0, strict=True)
    rate_card_version: NonEmpty
    max_output_tokens: int = Field(default=4000, gt=0, le=20000, strict=True)
    timeout_seconds: int = Field(default=90, gt=0, le=300, strict=True)


class Settings(Contract):
    schema_version: Literal[1] = 1
    database_url: str = "sqlite+pysqlite:///.local/delivery.db"
    temporal_address: NonEmpty = "127.0.0.1:7233"
    temporal_namespace: NonEmpty = "default"
    task_queue: NonEmpty = "agentic-delivery"
    artifact_root: Path = Path(".local/artifacts")
    repositories: tuple[RepositoryConfig, ...] = ()
    operators: tuple[Operator, ...] = ()
    budget: Budget = Budget()
    model: ModelConfig | None = None
    linear_organization_id: NonEmpty | None = None
    linear_webhook_secret_env: str = "LINEAR_WEBHOOK_SECRET"
    github_webhook_secret_env: str = "GITHUB_WEBHOOK_SECRET"
    github_installation_id: int | None = Field(default=None, gt=0)
    admissions_enabled: bool = True
    max_body_bytes: int = Field(default=262144, gt=0, le=1048576, strict=True)
    human_wait_seconds: int = Field(default=86400, gt=0, le=604800, strict=True)
    github_app_id: int | None = Field(default=None, gt=0)
    github_private_key_env: str = "GITHUB_APP_PRIVATE_KEY"
    publication_enabled: bool = False

    @model_validator(mode="after")
    def unique_identities(self) -> Self:
        for values in (
            [r.id for r in self.repositories],
            [o.id for o in self.operators],
            [o.token_sha256 for o in self.operators],
        ):
            if len(values) != len(set(values)):
                raise ValueError("Duplicate configuration identity")
        teams = [r.linear_team_id for r in self.repositories if r.linear_team_id]
        if len(teams) != len(set(teams)):
            raise ValueError("A Linear team must map to exactly one repository")
        known = {r.id for r in self.repositories}
        if any(set(o.repositories) - known for o in self.operators):
            raise ValueError("Operator refers to an unknown repository")
        if not self.database_url.startswith(("sqlite+pysqlite:", "postgresql+psycopg:")):
            raise ValueError("Unsupported database driver")
        return self

    def repository(self, identity: str) -> RepositoryConfig:
        for repository in self.repositories:
            if repository.id == identity:
                return repository
        raise ValueError("Repository is not onboarded")

    def execution_digest(self, identity: str) -> str:
        """Pin material execution settings without serializing secret values or operators."""
        material = {
            "repository": self.repository(identity).model_dump(mode="json"),
            "model": self.model.model_dump(mode="json") if self.model else None,
            "budget": self.budget.model_dump(mode="json"),
            "publication_enabled": self.publication_enabled,
            "github_app_id": self.github_app_id,
            "github_installation_id": self.github_installation_id,
            "policy_version": "controlled-prototype-v1",
        }
        return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def load_settings(path: Path | None = None) -> Settings:
    chosen = path or Path(os.environ.get("DELIVERY_CONFIG", "config.local.json"))
    if chosen.exists():
        return Settings.model_validate_json(chosen.read_text(encoding="utf-8"))
    if path is not None or "DELIVERY_CONFIG" in os.environ:
        raise ValueError("Configured settings file does not exist")
    return Settings()


def secret(name: str) -> str:
    value = os.environ.get(name)
    if not value or len(value) < 16:
        raise ValueError(f"Required secret environment variable is missing or too short: {name}")
    return value


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
