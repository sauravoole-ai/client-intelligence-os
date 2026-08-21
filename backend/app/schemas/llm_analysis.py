from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas.client_intelligence import (
    FindingClassification,
    RiskSeverity,
)


class LLMEvidenceBackedFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    category: str
    title: str
    statement: str
    classification: FindingClassification
    confidence: float = Field(ge=0, le=1)
    evidence_message_ids: list[str]


class LLMRiskFlag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_id: str
    title: str
    severity: RiskSeverity
    rationale: str
    classification: FindingClassification
    confidence: float = Field(ge=0, le=1)
    evidence_message_ids: list[str]


class LLMCoachAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str
    priority: int = Field(ge=1, le=5)
    action: str
    rationale: str
    classification: FindingClassification
    linked_finding_ids: list[str]
    evidence_message_ids: list[str]


class LLMAnalysisDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_period: str
    weekly_summary: LLMEvidenceBackedFinding
    findings: list[LLMEvidenceBackedFinding]
    risk_flags: list[LLMRiskFlag]
    recommended_actions: list[LLMCoachAction]
    missing_information: list[str]
