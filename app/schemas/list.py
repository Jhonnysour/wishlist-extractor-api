"""
Pydantic v2 schemas for lists (named groups of items).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ListCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ListUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ListResponse(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    item_count: int = 0

    model_config = {"from_attributes": True}
