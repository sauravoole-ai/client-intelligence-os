from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.schemas.client_intelligence import PersistedAnalysisResponse


ClientStatus = Literal["active", "archived"]


class ClientCreateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=255)
    external_reference: str | None = Field(default=None, max_length=255)

    @field_validator("display_name", mode="before")
    @classmethod
    def normalize_display_name(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        if not normalized:
            raise ValueError("display_name must not be blank")
        return normalized

    @field_validator("external_reference", mode="before")
    @classmethod
    def normalize_external_reference(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        return value.strip() or None


class ClientResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    display_name: str
    external_reference: str | None
    status: ClientStatus
    created_at: datetime
    updated_at: datetime


class ClientListResponse(BaseModel):
    items: list[ClientResponse]
    offset: int
    limit: int
    returned_count: int


class ClientAnalysisListResponse(BaseModel):
    items: list[PersistedAnalysisResponse]
    offset: int
    limit: int
    returned_count: int
