import asyncio
import os
import sys
from logging.config import fileConfig

from sqlalchemy import create_engine, pool
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context
from dotenv import load_dotenv

# ── path setup ────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

# ── imports ───────────────────────────────────────────────────────────────────
from common.settings import get_settings
from models.meta_models import RecordSnapshotEntity        # ← before BackupLogEntity
from models.meta_models import BackupLogEntity
from models.meta_models import RevertLogEntity
from common.lib.base_entity import BaseEntity

# ── alembic config ────────────────────────────────────────────────────────────
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = BaseEntity.metadata

# ── sync DSN for alembic (strip +asyncpg → use psycopg2 or plain postgresql) ──
SYNC_DB_URL = (
    f"postgresql://"
    f"{os.getenv('META_DB_USER')}:{os.getenv('META_DB_PASSWORD')}"
    f"@{os.getenv('META_DB_HOST')}:{os.getenv('META_DB_PORT')}"
    f"/{os.getenv('META_DB_NAME')}"
)

config.set_main_option("sqlalchemy.url", SYNC_DB_URL)


# ── offline mode ──────────────────────────────────────────────────────────────
def run_migrations_offline() -> None:
    context.configure(
        url=SYNC_DB_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# ── online mode (sync — alembic does not need async) ─────────────────────────
def run_migrations_online() -> None:
    connectable = create_engine(SYNC_DB_URL, poolclass=pool.NullPool, future=True)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()

    connectable.dispose()


# ── entry point ───────────────────────────────────────────────────────────────
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()