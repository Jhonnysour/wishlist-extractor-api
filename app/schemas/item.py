"""
Pydantic v2 schemas for request and response payloads.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class UrlInput(BaseModel):
    url: str


class ItemResponse(BaseModel):
    id: uuid.UUID
    original_url: str
    title: Optional[str] = None
    price: Optional[float] = None
    images: list[str] = Field(default_factory=list)
    status: str

    model_config = {"from_attributes": True}
