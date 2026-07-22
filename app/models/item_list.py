"""
ItemList model — a named list that groups items, owned by a user.

Named ItemList (not List) to avoid clashing with the builtin ``list``; maps to
the ``lists`` table.
"""

from __future__ import annotations

import uuid as _uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ItemList(Base):
    __tablename__ = "lists"

    id: Mapped[_uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[_uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
    )

    owner: Mapped["User"] = relationship(back_populates="lists")
    # passive_deletes: deleting a list cascades to its items via the DB FK
    # (items.list_id ON DELETE CASCADE), without ORM loading them first.
    items: Mapped[list["Item"]] = relationship(
        back_populates="item_list",
        passive_deletes=True,
    )
