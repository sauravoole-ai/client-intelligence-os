from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ActionItemStatus = Literal["open", "in_progress", "completed", "dismissed"]


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
    created_at: datetime
    updated_at: datetime
    version: int


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
