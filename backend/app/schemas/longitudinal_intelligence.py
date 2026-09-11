from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SignalKind(str, Enum):
    THEME = "theme"
    RISK = "risk"
    COMMITMENT = "commitment"
    PRIORITY = "priority"
    DECISION = "decision"


class TemporalState(str, Enum):
    EMERGING = "emerging"
    ACTIVE = "active"
    RECURRING = "recurring"
    RESOLVING = "resolving"
    RESOLVED = "resolved"
    REOPENED = "reopened"
    SUPERSEDED = "superseded"


class TrendDirection(str, Enum):
    IMPROVING = "improving"
    WORSENING = "worsening"
    STABLE = "stable"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class TrustState(str, Enum):
    DRAFT = "draft"
    TRUSTED = "trusted"
    REJECTED = "rejected"
    NEEDS_REVALIDATION = "needs_revalidation"


class EvidenceRole(str, Enum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    RESOLVES = "resolves"
    SUPERSEDES = "supersedes"


class RefreshSemanticStatus(str, Enum):
    NOT_NEEDED = "not_needed"
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"
    INVALID_OUTPUT = "invalid_output"


class SignalReviewAction(str, Enum):
    APPROVE = "approve"
    EDIT_AND_APPROVE = "edit_and_approve"
    REJECT = "reject"
    REVALIDATE = "revalidate"


class ArtifactKind(str, Enum):
    FINDING = "finding"
    RISK_FLAG = "risk_flag"
    RECOMMENDED_ACTION = "recommended_action"


class ActionEvidenceField(str, Enum):
    STATUS = "status"
    COMPLETED_AT = "completed_at"
    COMPLETION_OUTCOME = "completion_outcome"
    DUE_AT = "due_at"


class LongitudinalEvidenceReference(BaseModel):
    """A source locator supplied for a longitudinal proposal, never raw source text."""

    model_config = ConfigDict(extra="forbid")

    analysis_id: UUID | None = None
    action_item_id: UUID | None = None
    artifact_kind: ArtifactKind | None = None
    artifact_id: str | None = Field(default=None, min_length=1, max_length=255)
    message_id: str | None = Field(default=None, min_length=1, max_length=255)
    evidence_role: EvidenceRole
    action_field: ActionEvidenceField | None = None

    @field_validator("artifact_id", "message_id", mode="before")
    @classmethod
    def normalize_locator(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def require_exactly_one_source_family(self) -> "LongitudinalEvidenceReference":
        has_analysis = self.analysis_id is not None
        has_action_item = self.action_item_id is not None
        if has_analysis == has_action_item:
            raise ValueError("Evidence must identify exactly one source family.")
        if has_analysis:
            if self.artifact_kind is None or self.artifact_id is None:
                raise ValueError("Analysis evidence requires an artifact locator.")
            if self.action_field is not None:
                raise ValueError("Analysis evidence cannot include an Action Item field.")
        elif (
            self.artifact_kind is not None
            or self.artifact_id is not None
            or self.message_id is not None
            or self.action_field is None
        ):
            raise ValueError("Action Item evidence requires only an allowed Action Item field.")
        return self


class SignalReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: SignalReviewAction
    expected_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=2_000)
    summary: str | None = Field(default=None, min_length=1, max_length=500)
    explanation: str | None = Field(default=None, min_length=1, max_length=2_000)

    @field_validator("reason", "summary", "explanation", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_action_requirements(self) -> "SignalReviewRequest":
        if self.action in {SignalReviewAction.REJECT, SignalReviewAction.EDIT_AND_APPROVE}:
            if not self.reason:
                raise ValueError("A reason is required when rejecting or editing a signal.")
        if self.action is SignalReviewAction.EDIT_AND_APPROVE:
            if not self.summary or not self.explanation:
                raise ValueError("Edited approval requires a summary and explanation.")
        elif self.summary is not None or self.explanation is not None:
            raise ValueError("Summary and explanation are only allowed for edit_and_approve.")
        return self


class LLMLongitudinalProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_signal_id: UUID | None = None
    canonical_key: str | None = Field(default=None, min_length=1, max_length=255)
    signal_kind: SignalKind
    temporal_state: TemporalState
    trend_direction: TrendDirection
    summary: str = Field(min_length=1, max_length=500)
    explanation: str = Field(min_length=1, max_length=2_000)
    evidence: list[LongitudinalEvidenceReference] = Field(min_length=1, max_length=50)

    @field_validator("canonical_key", "summary", "explanation", mode="before")
    @classmethod
    def normalize_proposal_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def require_candidate_or_new_canonical_key(self) -> "LLMLongitudinalProposal":
        if (self.candidate_signal_id is None) == (self.canonical_key is None):
            raise ValueError("A proposal requires exactly one candidate signal ID or canonical key.")
        return self


class LLMLongitudinalProposalBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposals: list[LLMLongitudinalProposal] = Field(max_length=20)


class LongitudinalRefreshResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    processed_analysis_count: int = Field(ge=0)
    processed_action_item_count: int = Field(ge=0)
    created_draft_signal_count: int = Field(ge=0)
    updated_draft_signal_count: int = Field(ge=0)
    invalidated_trusted_signal_count: int = Field(ge=0)
    semantic_status: RefreshSemanticStatus


class LongitudinalSignalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    client_id: UUID
    canonical_key: str
    signal_kind: SignalKind
    temporal_state: TemporalState
    trend_direction: TrendDirection
    summary: str
    explanation: str
    trust_state: TrustState
    first_observed_at: datetime
    last_observed_at: datetime
    observation_count: int = Field(ge=1)
    version: int = Field(ge=1)
    reviewed_at: datetime | None = None
    evidence: list[LongitudinalEvidenceReference] = Field(default_factory=list)


class ActionItemAggregatesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    open_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)


class TrajectoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: UUID
    trusted_signals: list[LongitudinalSignalResponse] = Field(default_factory=list)
    review_required: list[LongitudinalSignalResponse] = Field(default_factory=list)
    action_item_aggregates: ActionItemAggregatesResponse
    deterministic_metrics: dict[str, int] = Field(default_factory=dict)


class WhatChangedItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal_id: UUID | None = None
    change_kind: Literal[
        "new",
        "recurring",
        "improving",
        "worsening",
        "completed",
        "resolved",
        "insufficient_history",
    ]
    summary: str
    evidence: list[LongitudinalEvidenceReference] = Field(default_factory=list)


class WhatChangedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: UUID
    comparison_analysis_id: UUID | None = None
    items: list[WhatChangedItemResponse] = Field(default_factory=list)
