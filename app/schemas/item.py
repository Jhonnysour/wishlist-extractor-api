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
    # Which list to add the item to. Optional for backward-compat: when absent,
    # the endpoint uses the user's default list.
    list_id: Optional[uuid.UUID] = None


class ItemUpdate(BaseModel):
    """Partial update of an item — only the fields sent are applied.

    ``images`` is a curated re-ordering/subset of the item's current images
    (first = cover); the endpoint rejects any URL that isn't already on the item.
    ``title`` lets the user rename the item (trimmed, non-empty).
    ``price`` lets the user type it in when no scraper could reach it — sending
    it explicitly as null clears it. Distinguishing "not sent" from "sent as
    null" is why the endpoint reads ``model_dump(exclude_unset=True)``.
    """

    purchased: Optional[bool] = None
    images: Optional[list[str]] = None
    title: Optional[str] = Field(default=None, max_length=255)
    price: Optional[float] = Field(default=None, ge=0)


class ItemFromHtml(BaseModel):
    """Rendered HTML captured by the client's WebView (Capa 0 fallback).

    The product URL is already stored on the item, so only the page HTML is
    sent. Used to extract data from pages that never serve their price to a
    server-side scraper.
    """

    html: str


class ItemResponse(BaseModel):
    id: uuid.UUID
    list_id: Optional[uuid.UUID] = None
    original_url: str
    title: Optional[str] = None
    price: Optional[float] = None
    images: list[str] = Field(default_factory=list)
    description: Optional[str] = None
    domain_source: Optional[str] = None
    status: str
    purchased: bool = False

    model_config = {"from_attributes": True}
