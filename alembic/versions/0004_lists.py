"""lists: named groups of items (+ default list per user, signup trigger)

Adds multiple named lists per user. Migrates existing data with zero loss:
creates a "Mi lista" per user and moves every existing item into it. list_id is
nullable (backward-compat during rollout; current code always sets it).

Revision ID: 0004_lists
Revises: 0003_supabase_auth
Create Date: 2026-07-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_lists"
down_revision: Union[str, Sequence[str], None] = "0003_supabase_auth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. lists table
    op.create_table(
        "lists",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )

    # 2. one default list per existing user
    op.execute(
        "INSERT INTO public.lists (user_id, name) "
        "SELECT id, 'Mi lista' FROM public.users;"
    )

    # 3. items.list_id (nullable, FK cascade)
    op.add_column(
        "items",
        sa.Column("list_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "items_list_id_fkey", "items", "lists", ["list_id"], ["id"],
        ondelete="CASCADE",
    )

    # 4. backfill: each item -> its owner's default list
    op.execute(
        "UPDATE public.items i SET list_id = l.id "
        "FROM public.lists l WHERE l.user_id = i.user_id;"
    )

    # 5. signup trigger also seeds the new user's default list
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.handle_new_auth_user()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public
        AS $$
        BEGIN
          INSERT INTO public.users (id, email, username)
          VALUES (NEW.id, NEW.email, NEW.raw_user_meta_data ->> 'username');
          INSERT INTO public.lists (user_id, name) VALUES (NEW.id, 'Mi lista');
          RETURN NEW;
        END;
        $$;
        """
    )


def downgrade() -> None:
    # revert the trigger to its 0003 form (no default list)
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.handle_new_auth_user()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public
        AS $$
        BEGIN
          INSERT INTO public.users (id, email, username)
          VALUES (NEW.id, NEW.email, NEW.raw_user_meta_data ->> 'username');
          RETURN NEW;
        END;
        $$;
        """
    )
    op.drop_constraint("items_list_id_fkey", "items", type_="foreignkey")
    op.drop_column("items", "list_id")
    op.drop_table("lists")
