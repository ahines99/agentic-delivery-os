"""A local change request is distinct from a GitHub pull request or merge."""

from typing import Literal

from pydantic import ConfigDict, Field

from agentic_delivery.domain.models import CommitSHA, Contract, NonEmpty


class DocumentationChangeRequest(Contract):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    schema_version: Literal["1"] = "1"
    kind: Literal["local_change_request"] = "local_change_request"
    state: Literal["OPEN"] = "OPEN"
    merge_state: Literal["UNMERGED"] = "UNMERGED"
    merge_authority: Literal["human_only"] = "human_only"
    auto_merge: Literal[False] = False
    workflow_id: NonEmpty
    repository_id: NonEmpty
    base_sha: CommitSHA
    head_sha: CommitSHA
    branch: NonEmpty
    path: NonEmpty
    content: str = Field(min_length=1, max_length=16000)
    approved_specification_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    policy_version: NonEmpty
