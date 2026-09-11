from uuid import UUID

import pytest

from backend.app.schemas.longitudinal_intelligence import LLMLongitudinalProposalBatch
from backend.app.services.longitudinal_inference_service import LongitudinalProposalValidationError, request_longitudinal_proposals, validate_longitudinal_proposals
from backend.app.services.groq_intelligence_service import IntelligenceProviderError
from backend.app.services.groq_intelligence_service import longitudinal_groq_transport_schema


def batch(locator: dict) -> LLMLongitudinalProposalBatch:
    return LLMLongitudinalProposalBatch.model_validate({"proposals": [{"canonical_key": "sleep", "signal_kind": "theme", "temporal_state": "active", "trend_direction": "unknown", "summary": "Sleep concern", "explanation": "Validated evidence", "evidence": [locator]}]})


def test_invented_evidence_locator_is_rejected() -> None:
    proposal = batch({"analysis_id": "00000000-0000-0000-0000-000000000001", "artifact_kind": "finding", "artifact_id": "invented", "evidence_role": "supports"})
    with pytest.raises(LongitudinalProposalValidationError, match="not valid"):
        validate_longitudinal_proposals(proposal, workspace_id="w", client_id="c", candidate_signal_ids=set(), analysis_locators=set(), action_facts=set())


def test_duplicate_proposals_collapse_to_one_canonical_candidate() -> None:
    locator = {"analysis_id": "00000000-0000-0000-0000-000000000001", "artifact_kind": "finding", "artifact_id": "f1", "evidence_role": "supports"}
    proposal = batch(locator)
    proposal.proposals.append(proposal.proposals[0])
    assert len(validate_longitudinal_proposals(proposal, workspace_id="w", client_id="c", candidate_signal_ids=set(), analysis_locators={("00000000-0000-0000-0000-000000000001", "finding", "f1", None)}, action_facts=set())) == 1


def test_longitudinal_transport_uses_a_dedicated_proposal_schema() -> None:
    schema = longitudinal_groq_transport_schema()
    assert "proposals" in schema["properties"]


def test_malformed_provider_json_returns_sanitized_failure() -> None:
    with pytest.raises(IntelligenceProviderError) as captured:
        request_longitudinal_proposals({"choices": [{"message": {"content": "not-json"}}]})
    assert str(captured.value) == "The intelligence provider is unavailable."


def test_invented_signal_id_is_rejected() -> None:
    proposal = LLMLongitudinalProposalBatch.model_validate({"proposals": [{"candidate_signal_id": "00000000-0000-0000-0000-000000000099", "signal_kind": "theme", "temporal_state": "active", "trend_direction": "unknown", "summary": "Sleep concern", "explanation": "Validated evidence", "evidence": [{"action_item_id": "00000000-0000-0000-0000-000000000001", "action_field": "status", "evidence_role": "supports"}]}]})
    with pytest.raises(LongitudinalProposalValidationError):
        validate_longitudinal_proposals(proposal, workspace_id="w", client_id="c", candidate_signal_ids=set(), analysis_locators=set(), action_facts={("00000000-0000-0000-0000-000000000001", "status")})


def test_invented_action_item_id_is_rejected() -> None:
    proposal = batch({"action_item_id": "00000000-0000-0000-0000-000000000099", "action_field": "status", "evidence_role": "supports"})
    with pytest.raises(LongitudinalProposalValidationError):
        validate_longitudinal_proposals(proposal, workspace_id="w", client_id="c", candidate_signal_ids=set(), analysis_locators=set(), action_facts=set())


def test_excessive_proposal_count_and_unsupported_taxonomy_are_rejected() -> None:
    item = {"canonical_key": "sleep", "signal_kind": "theme", "temporal_state": "active", "trend_direction": "unknown", "summary": "Sleep concern", "explanation": "Validated evidence", "evidence": [{"action_item_id": "00000000-0000-0000-0000-000000000001", "action_field": "status", "evidence_role": "supports"}]}
    with pytest.raises(Exception):
        LLMLongitudinalProposalBatch.model_validate({"proposals": [item] * 21})
    item["signal_kind"] = "unbounded_kind"
    with pytest.raises(Exception):
        LLMLongitudinalProposalBatch.model_validate({"proposals": [item]})


def test_wrong_workspace_candidate_signal_is_rejected() -> None:
    proposal = LLMLongitudinalProposalBatch.model_validate({"proposals": [{"candidate_signal_id": "00000000-0000-0000-0000-000000000010", "signal_kind": "theme", "temporal_state": "active", "trend_direction": "unknown", "summary": "Sleep concern", "explanation": "Validated evidence", "evidence": [{"action_item_id": "00000000-0000-0000-0000-000000000001", "action_field": "status", "evidence_role": "supports"}]}]})
    with pytest.raises(LongitudinalProposalValidationError):
        validate_longitudinal_proposals(proposal, workspace_id="w", client_id="c", candidate_signal_ids={"00000000-0000-0000-0000-000000000010"}, analysis_locators=set(), action_facts={("00000000-0000-0000-0000-000000000001", "status")}, candidate_signal_context={"00000000-0000-0000-0000-000000000010": ("other", "c")})
