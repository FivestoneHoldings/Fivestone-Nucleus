"""Pydantic contracts — mirror GWD-003 envelope law."""
from datetime import datetime
from pydantic import BaseModel, Field


class EventIn(BaseModel):
    event_type: str = Field(..., min_length=3, max_length=120, pattern=r"^[a-z0-9_]+\.[a-z0-9_.]+$")
    entity_ref: str = Field(..., min_length=1, max_length=120)
    tenant: str = Field(default="gateway", max_length=60)
    actor: str = Field(default="system", max_length=120)
    occurred_at: datetime | None = None
    payload: str = Field(default="{}")


class EventOut(BaseModel):
    id: str
    event_type: str
    entity_ref: str
    tenant: str
    actor: str
    occurred_at: datetime
    recorded_at: datetime
    payload: str

    model_config = {"from_attributes": True}


class ErrorEnvelope(BaseModel):
    """GWD-003 §2 error envelope law."""
    error: str
    detail: str | None = None
    ref: str | None = None
