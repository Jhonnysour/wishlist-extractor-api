"""
Pydantic v2 schemas for request and response payloads.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl


class UrlInput(BaseModel):
    url: HttpUrl


class ItemUpdate(BaseModel):
    """Fields the user can change on an existing item."""

    purchased: bool


class ItemFromHtml(BaseModel):
    """Rendered HTML captured by the client's WebView (Capa 0 fallback).

    The product URL is already stored on the item, so only the page HTML is
    sent. Used to extract data from pages that never serve their price to a
    server-side scraper.
    """

    html: str


class ItemResponse(BaseModel):
    id: uuid.UUID
    original_url: str
    title: Optional[str] = None
    price: Optional[float] = None
    images: list[str] = Field(default_factory=list)
    description: Optional[str] = None
    domain_source: Optional[str] = None
    status: str
    purchased: bool = False

    model_config = {"from_attributes": True}
