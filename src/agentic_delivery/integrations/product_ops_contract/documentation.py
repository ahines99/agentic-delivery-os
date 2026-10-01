"""Optional, digest-pinned policy for a single add-only documentation operation.

This is trusted deployment policy, never a tool or permission emitted by a model.
Consumers must enforce this capability instead of invoking a general code agent.
"""

import hashlib
import json
import re
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


def canonical(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def semantic_digest(spec: dict[str, Any]) -> str:
    body = json.loads(json.dumps(spec))
    for field in ("revision", "content_digest", "risk"):
        body.pop(field)
    body["approval_policy"].pop("policy_version")
    for work in body["work_items"]:
        work.pop("risk_tier")
    return canonical(body)


class DocumentationCapability(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    kind: Literal["add-documentation-v1"] = "add-documentation-v1"
    semantic_digest: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    repository_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")]
    base_sha: Annotated[str, Field(pattern=r"^[a-f0-9]{40}$")]
    path: Annotated[str, Field(pattern=r"^docs/[a-z0-9][a-z0-9_-]{0,80}\.md$")]
    content: Annotated[str, Field(min_length=1, max_length=16000)]

    @model_validator(mode="after")
    def inert_document(self) -> Self:
        # No templates, executable fences, HTML, links, control characters or agent
        # instruction filenames in this deliberately narrow initial capability.
        if (
            self.path.casefold() in {"docs/agents.md", "docs/claude.md", "docs/copilot.md"}
            or any(c in self.content for c in ("\r", "\x00", "<", ">", "`", "[", "]"))
            or any(ord(c) < 32 and c != "\n" for c in self.content)
            or re.search(r"(?i)(?:https?://|file:|javascript:)", self.content)
            or not self.content.endswith("\n")
        ):
            raise ValueError("capability requires inert plain Markdown with a trailing LF")
        return self

    @property
    def policy_version(self) -> str:
        return "doc-add-v1-" + canonical(self.model_dump(mode="json"))

    def validate_specification(self, spec: dict[str, Any]) -> None:
        self.model_validate_json(self.model_dump_json())
        context = spec.get("repository_context")
        source = spec["source_statements"][0]["text"]
        if (
            semantic_digest(spec) != self.semantic_digest
            or not context
            or context["repository_id"] != self.repository_id
            or len(spec["work_items"]) != 1
            or spec["dependencies"]
            or spec["work_items"][0]["repository_id"] != self.repository_id
            or self.path not in source
            or self.content not in source
            or any(q["blocking"] and q["resolution"] is None for q in spec["unresolved_questions"])
        ):
            raise ValueError("documentation capability does not bind this exact requested work")
