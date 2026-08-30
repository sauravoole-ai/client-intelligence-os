from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas.client_intelligence import (
    FindingClassification,
    RiskSeverity,
)


ShortText = Annotated[str, Field(min_length=1, max_length=255)]
DescriptiveText = Annotated[str, Field(min_length=1, max_length=2_000)]


class LLMEvidenceBackedFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: ShortText
    category: ShortText
    title: ShortText
    statement: DescriptiveText
    classification: FindingClassification
    confidence: float = Field(ge=0, le=1)
    evidence_message_ids: list[ShortText] = Field(max_length=10)


class LLMRiskFlag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_id: ShortText
    title: ShortText
    severity: RiskSeverity
    rationale: DescriptiveText
    classification: FindingClassification
    confidence: float = Field(ge=0, le=1)
    evidence_message_ids: list[ShortText] = Field(max_length=10)


class LLMCoachAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: ShortText
    priority: int = Field(ge=1, le=5)
    action: DescriptiveText
    rationale: DescriptiveText
    classification: FindingClassification
    linked_finding_ids: list[ShortText] = Field(max_length=10)
    evidence_message_ids: list[ShortText] = Field(max_length=10)


class LLMAnalysisDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_period: ShortText
    weekly_summary: LLMEvidenceBackedFinding
    findings: list[LLMEvidenceBackedFinding] = Field(max_length=20)
    risk_flags: list[LLMRiskFlag] = Field(max_length=10)
    recommended_actions: list[LLMCoachAction] = Field(max_length=10)
    missing_information: list[DescriptiveText] = Field(max_length=20)
