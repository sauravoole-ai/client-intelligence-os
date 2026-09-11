from importlib import import_module

import pytest
from pydantic import ValidationError


def longitudinal_contracts() -> object:
    return import_module("backend.app.schemas.longitudinal_intelligence")


def valid_analysis_evidence() -> dict[str, object]:
    return {
        "analysis_id": "00000000-0000-4000-8000-000000000101",
        "artifact_kind": "finding",
        "artifact_id": "finding-1",
        "evidence_role": "supports",
    }


def test_signal_review_reject_requires_reason() -> None:
    contracts = longitudinal_contracts()

    with pytest.raises(ValidationError, match="reason"):
        contracts.SignalReviewRequest(action="reject", expected_version=1)


def test_edit_and_approve_requires_bounded_summary_and_explanation() -> None:
    contracts = longitudinal_contracts()

    with pytest.raises(ValidationError, match="reason"):
        contracts.SignalReviewRequest(
            action="edit_and_approve",
            expected_version=1,
            summary="Updated summary",
            explanation="Updated explanation",
        )

    with pytest.raises(ValidationError):
        contracts.SignalReviewRequest(
            action="edit_and_approve",
            expected_version=1,
            reason="Corrected after reviewing the source.",
            summary="x" * 501,
            explanation="Updated explanation",
        )

    with pytest.raises(ValidationError):
        contracts.SignalReviewRequest(
            action="edit_and_approve",
            expected_version=1,
            reason="Corrected after reviewing the source.",
            summary="Updated summary",
            explanation="x" * 2_001,
        )


def test_llm_batch_rejects_extra_fields_and_unsupported_taxonomy() -> None:
    contracts = longitudinal_contracts()
    proposal = {
        "canonical_key": "career-transition",
        "signal_kind": "theme",
        "temporal_state": "emerging",
        "trend_direction": "unknown",
        "summary": "Career transition is newly discussed.",
        "explanation": "The approved finding identifies a new transition.",
        "evidence": [valid_analysis_evidence()],
    }

    with pytest.raises(ValidationError):
        contracts.LLMLongitudinalProposalBatch(
            proposals=[{**proposal, "confidence": 0.98}]
        )

    with pytest.raises(ValidationError):
        contracts.LLMLongitudinalProposalBatch(
            proposals=[{**proposal, "signal_kind": "personality"}]
        )


def test_evidence_reference_requires_exactly_one_source_contract() -> None:
    contracts = longitudinal_contracts()

    analysis_evidence = contracts.LongitudinalEvidenceReference(
        **valid_analysis_evidence()
    )
    assert analysis_evidence.analysis_id is not None
    assert analysis_evidence.action_item_id is None

    action_evidence = contracts.LongitudinalEvidenceReference(
        action_item_id="00000000-0000-4000-8000-000000000102",
        evidence_role="supports",
        action_field="status",
    )
    assert action_evidence.action_item_id is not None
    assert action_evidence.analysis_id is None

    with pytest.raises(ValidationError):
        contracts.LongitudinalEvidenceReference(
            **valid_analysis_evidence(),
            action_item_id="00000000-0000-4000-8000-000000000102",
            action_field="status",
        )

    with pytest.raises(ValidationError):
        contracts.LongitudinalEvidenceReference(
            action_item_id="00000000-0000-4000-8000-000000000102",
            evidence_role="supports",
        )
