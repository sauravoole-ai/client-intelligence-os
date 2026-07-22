from pydantic import BaseModel, Field

from backend.app.schemas.client_intelligence import (
    FindingClassification,
    RiskSeverity,
)


class LLMEvidenceBackedFinding(BaseModel):
    finding_id: str
    category: str
    title: str
    statement: str
    classification: FindingClassification
    confidence: float = Field(ge=0, le=1)
    evidence_message_ids: list[str] = Field(default_factory=list)


class LLMRiskFlag(BaseModel):
    risk_id: str
    title: str
    severity: RiskSeverity
    rationale: str
    classification: FindingClassification
    confidence: float = Field(ge=0, le=1)
    evidence_message_ids: list[str] = Field(default_factory=list)


class LLMCoachAction(BaseModel):
    action_id: str
    priority: int = Field(ge=1, le=5)
    action: str
    rationale: str
    classification: FindingClassification
    linked_finding_ids: list[str] = Field(default_factory=list)
    evidence_message_ids: list[str] = Field(default_factory=list)


class LLMAnalysisDraft(BaseModel):
    analysis_period: str
    weekly_summary: LLMEvidenceBackedFinding
    findings: list[LLMEvidenceBackedFinding] = Field(default_factory=list)
    risk_flags: list[LLMRiskFlag] = Field(default_factory=list)
    recommended_actions: list[LLMCoachAction] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
