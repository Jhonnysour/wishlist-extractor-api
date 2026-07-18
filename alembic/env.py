import asyncio
import os
from logging.config import fileConfig

from dotenv import load_dotenv
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

# Load DATABASE_URL / secrets from .env, same as the app does.
load_dotenv()

# Import the app's declarative Base and every model module so that all tables
# register on Base.metadata — this is what --autogenerate compares against.
from app.core.database import Base  # noqa: E402
from app.models import item, user  # noqa: E402,F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# The async DB URL (postgresql+asyncpg://...) comes from the environment, never
# from alembic.ini, so migrations hit the same database as the running app.
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set in the environment / .env")


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a live connection)."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # compare_type=False on purpose: our columns use unlength'd String, which
        # Postgres stores as TEXT/VARCHAR. compare_type=True reports those as
        # spurious "type changes" on every autogenerate. Real type changes are
        # rare here and get hand-written when needed.
        compare_type=False,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=False,  # see note in run_migrations_offline
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations through it."""
    connectable = create_async_engine(
        DATABASE_URL,
        poolclass=pool.NullPool,
        # Supabase runs behind pgbouncer; disable the prepared-statement cache
        # exactly like app.core.database does, or asyncpg errors on the pooler.
        connect_args={"statement_cache_size": 0},
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
