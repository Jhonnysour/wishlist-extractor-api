"""
Item model — maps to the ``items`` table in PostgreSQL.
"""

from __future__ import annotations

import uuid as _uuid
from typing import Optional

from sqlalchemy import ARRAY, Boolean, DateTime, ForeignKey, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Item(Base):
    __tablename__ = "items"

    id: Mapped[_uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[_uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
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
    # User-facing flag (crossed-out in the app), orthogonal to the scraping
    # ``status``. Set via PATCH once the user has bought the item.
    purchased: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=text("false"),
    )
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
    )

    owner: Mapped["User"] = relationship(back_populates="items")
