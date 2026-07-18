"""move auth to Supabase: sync trigger + username RPCs, drop local passwords

Consolidates authentication onto Supabase Auth (GoTrue):
  * wipes the old test rows in public.users (their emails would collide with
    fresh Supabase sign-ups; items cascade-delete with them);
  * drops public.users.hashed_password (Supabase owns the password now);
  * a trigger mirrors every new auth.users row into public.users;
  * get_email_by_username lets the client resolve username -> email before
    signInWithPassword (login stays username-based);
  * check_username_available lets the client pre-check before signUp.

Revision ID: 0003_supabase_auth
Revises: 0002_items_notnull
Create Date: 2026-07-17
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0003_supabase_auth"
down_revision: Union[str, Sequence[str], None] = "0002_items_notnull"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Old test users would collide by email with Supabase sign-ups. Items
    # cascade-delete via items.user_id ON DELETE CASCADE.
    op.execute("DELETE FROM public.users")

    # Supabase Auth owns the password; the local hash is obsolete.
    op.drop_column("users", "hashed_password")

    # username -> email, so the client can keep a username login on top of
    # Supabase's email-based signInWithPassword. SECURITY DEFINER + a narrow
    # grant let the anon role call just this, without table access.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.get_email_by_username(p_username text)
        RETURNS text
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = public
        AS $$
          SELECT email FROM public.users WHERE username = p_username LIMIT 1;
        $$;
        """
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.get_email_by_username(text) TO anon;"
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.check_username_available(p_username text)
        RETURNS boolean
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = public
        AS $$
          SELECT NOT EXISTS (
            SELECT 1 FROM public.users WHERE username = p_username
          );
        $$;
        """
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.check_username_available(text) TO anon;"
    )

    # Mirror new Supabase users into public.users. Runs in the same transaction
    # as the auth.users insert, so a duplicate username (UNIQUE) aborts the whole
    # sign-up cleanly — no orphan auth user without a public profile.
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
          VALUES (
            NEW.id,
            NEW.email,
            NEW.raw_user_meta_data ->> 'username'
          );
          RETURN NEW;
        END;
        $$;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;")
    op.execute(
        """
        CREATE TRIGGER on_auth_user_created
          AFTER INSERT ON auth.users
          FOR EACH ROW EXECUTE FUNCTION public.handle_new_auth_user();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;")
    op.execute("DROP FUNCTION IF EXISTS public.handle_new_auth_user();")
    op.execute("DROP FUNCTION IF EXISTS public.check_username_available(text);")
    op.execute("DROP FUNCTION IF EXISTS public.get_email_by_username(text);")
    # Re-add the column (nullable — the old hashes cannot be recovered).
    op.add_column(
        "users",
        sa.Column("hashed_password", sa.String(length=255), nullable=True),
    )
