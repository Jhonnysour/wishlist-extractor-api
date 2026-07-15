"""
Item model — maps to the ``items`` table in PostgreSQL.
"""

from __future__ import annotations

import uuid as _uuid
from typing import Optional

from sqlalchemy import ARRAY, DateTime, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Item(Base):
    __tablename__ = "items"

    id: Mapped[_uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    original_url: Mapped[str]
    domain_source: Mapped[Optional[str]]
    title: Mapped[Optional[str]]
    description: Mapped[Optional[str]]
    price: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    images: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        default=list,
    )
    status: Mapped[str] = mapped_column(default="PENDING")
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
    )
