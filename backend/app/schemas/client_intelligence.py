from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class FindingClassification(str, Enum):
    CONFIRMED_FACT = "confirmed_fact"
    CLIENT_REPORTED = "client_reported_information"
    AI_INFERENCE = "ai_generated_inference"
    MISSING = "missing_unavailable_information"


class ReviewStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    EDITED = "edited"
    REJECTED = "rejected"


class RiskSeverity(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EvidenceReference(BaseModel):
    message_id: str
    day: str
    speaker: str
    quote: str = Field(min_length=1)


class Finding(BaseModel):
    finding_id: str
    category: str
    title: str
    statement: str
    classification: FindingClassification
    confidence: float = Field(ge=0, le=1)
    evidence: list[EvidenceReference] = Field(default_factory=list)
    review_status: ReviewStatus = ReviewStatus.PENDING


class RiskFlag(BaseModel):
    risk_id: str
    title: str
    severity: RiskSeverity
    rationale: str
    classification: FindingClassification = FindingClassification.AI_INFERENCE
    confidence: float = Field(ge=0, le=1)
    evidence: list[EvidenceReference] = Field(default_factory=list)
    review_status: ReviewStatus = ReviewStatus.PENDING


class CoachAction(BaseModel):
    action_id: str
    priority: int = Field(ge=1, le=5)
    action: str
    rationale: str
    classification: FindingClassification = FindingClassification.AI_INFERENCE
    linked_finding_ids: list[str] = Field(default_factory=list)
    evidence: list[EvidenceReference] = Field(default_factory=list)
    review_status: ReviewStatus = ReviewStatus.PENDING


class AnalysisRequest(BaseModel):
    conversation: str = Field(
        min_length=20,
        description="An anonymised client-coach conversation.",
    )
    client_reference: str | None = Field(
        default=None,
        description="An anonymised internal client reference.",
    )
    analysis_period: str | None = None
    engine_mode: Literal["auto", "llm", "deterministic"] = "auto"


class AnalysisResponse(BaseModel):
    analysis_id: UUID
    status: Literal["completed"]
    created_at: datetime
    client_reference: str | None
    analysis_period: str
    weekly_summary: Finding
    findings: list[Finding]
    risk_flags: list[RiskFlag]
    recommended_actions: list[CoachAction]
    missing_information: list[str]
    engine: str
    prompt_version: str = "deterministic-baseline-v1"
    validation_warnings: list[str] = Field(default_factory=list)
    fallback_reason: str | None = None
