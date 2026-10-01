"""Bind original hypothetical disputes to current owned runtime evidence, without model effects."""

from dataclasses import dataclass

from agentic_delivery.evaluation.semantic_adjudication import (
    AdjudicationStructureFailure,
    ExecutedOwnedAdjudicationContext,
    OwnedAuthoredAdjudicationContext,
    _require,
    disputed_targets,
)
from agentic_delivery.evaluation.semantic_adjudication_examples import (
    validate_authored_adjudication_context,
)
from agentic_delivery.evaluation.semantic_examples import SemanticSubject
from agentic_delivery.evaluation.semantic_owned_context import OwnedSemanticContextAuthority
from agentic_delivery.evaluation.semantic_scoring import (
    FrozenOwnedSemanticEvidence,
    SemanticScoringContext,
)
from agentic_delivery.storage.artifacts import ArtifactStore


@dataclass(frozen=True, kw_only=True)
class OwnedAdjudicationContextAuthority:
    """Pinned context identity and original peer artifact plus a concrete current runtime reader.

    This authority validates owned input provenance only. It does not authorize a model,
    adjudication calibration, historical scoring, admission, or a paid operation.
    """

    owned_authority: OwnedSemanticContextAuthority
    authored_artifacts: ArtifactStore
    authored_context_artifact: str
    context_id: str
    rubric_artifact: str

    def _authored(self) -> OwnedAuthoredAdjudicationContext:
        _require(isinstance(self.owned_authority, OwnedSemanticContextAuthority))
        _require(isinstance(self.authored_artifacts, ArtifactStore))
        worker = self.owned_authority.runtime.worker_root.resolve()
        root = self.authored_artifacts.root.resolve()
        _require(not root.is_relative_to(worker) and not worker.is_relative_to(root))
        original = validate_authored_adjudication_context(
            self.authored_context_artifact, subjects=self.authored_artifacts
        )
        _require(isinstance(self.context_id, str) and self.context_id == self.context_id.strip())
        _require(0 < len(self.context_id) <= 200)
        _require(self.context_id not in {original.context_id, *(p.peer_id for p in original.peers)})
        authored_subject = SemanticSubject.model_validate_json(
            self.authored_artifacts.get(original.evidence.subject_artifact)
        )
        actual_subject = SemanticSubject.model_validate_json(
            self.owned_authority.runtime.subject_artifacts.get(
                self.owned_authority.request.subject_artifact
            )
        )
        _require(authored_subject == actual_subject)
        return original

    def _bind(
        self, original: OwnedAuthoredAdjudicationContext, initial: SemanticScoringContext
    ) -> ExecutedOwnedAdjudicationContext:
        _require(isinstance(initial.evidence, FrozenOwnedSemanticEvidence))
        assert isinstance(initial.evidence, FrozenOwnedSemanticEvidence)
        material, evidence = original.evidence, initial.evidence
        authored_subject = SemanticSubject.model_validate_json(
            self.authored_artifacts.get(material.subject_artifact)
        )
        actual_subject = SemanticSubject.model_validate_json(
            self.owned_authority.runtime.subject_artifacts.get(evidence.subject_artifact)
        )
        # The existing stores use different JSON encodings; compare the entire strictly
        # parsed original subject, while retaining both exact immutable artifact identities.
        _require(authored_subject == actual_subject)
        for field in (
            "subject_id",
            "authorship",
            "requirements",
            "criteria",
            "source_snapshot_artifact",
            "source_files",
            "candidate_artifact",
            "candidate_files",
            "oracle_artifact",
            "oracle_files",
        ):
            _require(getattr(material, field) == getattr(evidence, field))
        context = ExecutedOwnedAdjudicationContext(
            context_id=self.context_id,
            authored_context_artifact=self.authored_context_artifact,
            evidence=evidence,
            evidence_digest=initial.evidence_digest,
            peers=original.peers,
        )
        _require(disputed_targets(context) == disputed_targets(original))
        return context

    def assemble(self) -> ExecutedOwnedAdjudicationContext:
        """Prepare only idempotent source projections; no code, grant, account or model call."""
        try:
            original = self._authored()
            # scorer_a selects the existing projection API only; no initial review is made.
            initial = self.owned_authority.assemble(
                stage="scorer_a", context_id=self.context_id, rubric_artifact=self.rubric_artifact
            )
            result = self._bind(original, initial)
            _require(self._authored() == original)
            self.owned_authority.validate(initial)
            return result
        except Exception:
            raise AdjudicationStructureFailure(
                "Owned adjudication inputs are unavailable"
            ) from None

    def validate(self, context: ExecutedOwnedAdjudicationContext) -> None:
        """Read-only exact reconstruction, current runtime/policy and pinned identity checks."""
        try:
            context = ExecutedOwnedAdjudicationContext.model_validate(
                context.model_dump(mode="json")
            )
            _require(context.context_id == self.context_id)
            _require(context.authored_context_artifact == self.authored_context_artifact)
            _require(context.evidence.rubric_artifact == self.rubric_artifact)
            original = self._authored()
            initial = SemanticScoringContext(
                purpose="OWNED_DEVELOPMENT_CALIBRATION",
                stage="scorer_a",
                context_id=self.context_id,
                evidence=context.evidence,
                evidence_digest=context.evidence_digest,
            )
            self.owned_authority.validate(initial)
            _require(self._bind(original, initial) == context)
            _require(self._authored() == original)
            self.owned_authority.validate(initial)
        except Exception:
            raise AdjudicationStructureFailure("Owned adjudication reconstruction failed") from None
