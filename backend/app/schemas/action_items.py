from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import AliasPath, BaseModel, ConfigDict, Field, field_validator, model_validator


ActionItemStatus = Literal["open", "in_progress", "completed", "dismissed"]
ActionQueue = Literal[
    "open",
    "due_today",
    "overdue",
    "upcoming",
    "completed",
    "no_due_date",
]


class AssigneeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    membership_id: str = Field(validation_alias="id")
    display_name: str | None = Field(validation_alias=AliasPath("user", "display_name"))
    email: str | None = Field(validation_alias=AliasPath("user", "email"))
    role: Literal["owner", "member"]
    status: Literal["active", "disabled"]


class WorkspaceMemberResponse(BaseModel):
    membership_id: str
    display_name: str | None
    email: str | None
    role: Literal["owner", "member"]


class WorkspaceMemberListResponse(BaseModel):
    items: list[WorkspaceMemberResponse]


class MaterializeActionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_action_ids: list[str] = Field(min_length=1, max_length=50)

    @field_validator("source_action_ids", mode="before")
    @classmethod
    def normalize_ids(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return [item.strip() if isinstance(item, str) else item for item in value]

    @model_validator(mode="after")
    def validate_ids(self) -> "MaterializeActionsRequest":
        if any(not item or len(item) > 255 for item in self.source_action_ids):
            raise ValueError("source_action_ids must contain nonblank IDs up to 255 characters")
        if len(set(self.source_action_ids)) != len(self.source_action_ids):
            raise ValueError("source_action_ids must not contain duplicates")
        return self


class ActionItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    analysis_id: UUID
    client_id: UUID | None
    source_action_id: str
    title: str
    description: str
    priority: int
    status: ActionItemStatus
    linked_finding_ids: list[str]
    due_at: datetime | None
    completed_at: datetime | None
    assignee_membership_id: str | None
    completion_outcome: str | None
    assignee: AssigneeResponse | None = Field(
        default=None, validation_alias="assignee_membership"
    )
    created_at: datetime
    updated_at: datetime
    version: int

    @field_validator("due_at", "completed_at")
    @classmethod
    def normalize_datetime_for_response(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class MaterializeActionsResponse(BaseModel):
    analysis_id: UUID
    items: list[ActionItemResponse]
    created_count: int
    existing_count: int


class ActionItemListResponse(BaseModel):
    items: list[ActionItemResponse]
    offset: int
    limit: int
    returned_count: int


class ActionStatusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ActionItemStatus
    expected_version: int = Field(ge=1)
    completion_outcome: str | None = Field(default=None, max_length=2000)

    @field_validator("completion_outcome", mode="before")
    @classmethod
    def normalize_completion_outcome(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

class ActionFollowUpUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignee_membership_id: str | None = Field(min_length=36, max_length=36)
    due_at: datetime | None
    expected_version: int = Field(ge=1)

    @field_validator("due_at")
    @classmethod
    def require_timezone_aware_due_at(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("due_at must include a timezone offset")
        return value
