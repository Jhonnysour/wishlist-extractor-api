"""items.images and items.status NOT NULL

Reconciles a real drift: the app always populates these (images defaults to [],
status to PENDING), but the columns were created nullable. The wishlist has 0
rows with NULL in either, so tightening is safe. This is the first change applied
purely through the migration workflow (no manual ALTER).

Revision ID: 0002_items_notnull
Revises: 0001_baseline
Create Date: 2026-07-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_items_notnull"
down_revision: Union[str, Sequence[str], None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "items",
        "images",
        existing_type=postgresql.ARRAY(sa.Text()),
        nullable=False,
        existing_server_default=sa.text("'{}'::text[]"),
    )
    op.alter_column(
        "items",
        "status",
        existing_type=sa.String(length=50),
        nullable=False,
        existing_server_default=sa.text("'PENDING'::character varying"),
    )


def downgrade() -> None:
    op.alter_column(
        "items",
        "status",
        existing_type=sa.String(length=50),
        nullable=True,
        existing_server_default=sa.text("'PENDING'::character varying"),
    )
    op.alter_column(
        "items",
        "images",
        existing_type=postgresql.ARRAY(sa.Text()),
        nullable=True,
        existing_server_default=sa.text("'{}'::text[]"),
    )
