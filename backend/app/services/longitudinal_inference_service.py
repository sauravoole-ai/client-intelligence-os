"""Strict, server-owned validation for longitudinal semantic proposals."""

from collections.abc import Iterable, Mapping
import json

import httpx

from backend.app.schemas.longitudinal_intelligence import LLMLongitudinalProposal, LLMLongitudinalProposalBatch
from backend.app.services.groq_intelligence_service import IntelligenceProviderError


class LongitudinalProposalValidationError(ValueError):
    """Sanitized rejection of an untrusted provider proposal."""


def validate_longitudinal_proposals(
    batch: LLMLongitudinalProposalBatch,
    *,
    workspace_id: str,
    client_id: str,
    candidate_signal_ids: set[str],
    analysis_locators: set[tuple[str, str, str, str | None]],
    action_facts: set[tuple[str, str]],
    candidate_signal_context: Mapping[str, tuple[str, str]] | None = None,
    analysis_versions: Mapping[str, int] | None = None,
    action_versions: Mapping[str, int] | None = None,
) -> list[LLMLongitudinalProposal]:
    accepted: list[LLMLongitudinalProposal] = []
    seen: set[tuple[str, str]] = set()
    for proposal in batch.proposals:
        if proposal.candidate_signal_id is not None and str(proposal.candidate_signal_id) not in candidate_signal_ids:
            raise LongitudinalProposalValidationError("The longitudinal proposal is not valid.")
        if proposal.candidate_signal_id is not None and candidate_signal_context is not None:
            if candidate_signal_context.get(str(proposal.candidate_signal_id)) != (workspace_id, client_id):
                raise LongitudinalProposalValidationError("The longitudinal proposal is not valid.")
        for evidence in proposal.evidence:
            if evidence.analysis_id is not None:
                locator = (str(evidence.analysis_id), evidence.artifact_kind.value, evidence.artifact_id or "", evidence.message_id)
                if locator not in analysis_locators:
                    raise LongitudinalProposalValidationError("The longitudinal proposal is not valid.")
                if analysis_versions is not None and str(evidence.analysis_id) not in analysis_versions:
                    raise LongitudinalProposalValidationError("The longitudinal proposal is not valid.")
            elif (str(evidence.action_item_id), evidence.action_field.value) not in action_facts:
                raise LongitudinalProposalValidationError("The longitudinal proposal is not valid.")
            elif action_versions is not None and str(evidence.action_item_id) not in action_versions:
                raise LongitudinalProposalValidationError("The longitudinal proposal is not valid.")
        identity = (str(proposal.candidate_signal_id or ""), proposal.canonical_key or "")
        if identity not in seen:
            seen.add(identity); accepted.append(proposal)
    return accepted


def request_longitudinal_proposals(
    response_body: object,
) -> LLMLongitudinalProposalBatch:
    """Parse a mock/provider structured payload without exposing its details."""
    try:
        content = response_body["choices"][0]["message"]["content"]  # type: ignore[index]
        return LLMLongitudinalProposalBatch.model_validate(json.loads(content))
    except Exception as error:
        raise IntelligenceProviderError(category="invalid_response") from error
