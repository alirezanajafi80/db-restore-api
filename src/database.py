"""
src/core/database.py

Manages THREE async database connections:
  1. main_db   — the live production database (read + write)
  2. backup_db — the backup database (read only; dynamic per request)
  3. meta_db   — stores BackupLog / RevertLog audit trail for this src

The backup engine is created DYNAMICALLY per request based on:
  - backup_db_name param  →  same host as default backup but different DB
  - no param              →  uses default backup DSN from settings

We use a simple LRU engine cache keyed by DSN to avoid recreating
SQLAlchemy engines on every request.
"""

import logging
from functools import lru_cache
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from src.commen.settings import get_settings


logger = logging.getLogger(__name__)
settings = get_settings()


# ── Engine factory (cached by DSN) ───────────────────────────────────────────
@lru_cache(maxsize=32)
def _get_engine(dsn: str, pool_size: int = 5) -> AsyncEngine:
    """Create (or return cached) async engine for a given DSN."""
    logger.info("Creating engine for DSN: %s", dsn.split("@")[-1])   # hide password
    return create_async_engine(
        dsn,
        pool_size=pool_size,
        max_overflow=10,
        pool_pre_ping=True,
        echo=settings.APP_ENV == "development",
    )


# ── Named engines (startup) ───────────────────────────────────────────────────

def get_main_engine() -> AsyncEngine:
    return _get_engine(settings.main_db_dsn, pool_size=10)


def get_meta_engine() -> AsyncEngine:
    return _get_engine(settings.meta_db_dsn, pool_size=5)


def get_backup_engine(backup_db_name: str | None = None) -> AsyncEngine:
    """
    Return async engine for the backup database.

    If backup_db_name is given → connect to that DB on the backup host.
    If None → use the default backup DB from settings.
    """
    if backup_db_name:
        dsn = settings.build_backup_dsn(backup_db_name)
    else:
        dsn = settings.default_backup_db_dsn
    return _get_engine(dsn, pool_size=5)


# ── Session factories ─────────────────────────────────────────────────────────

def _make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        engine,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )


# Fixed meta_session factories for main + meta
MainSessionFactory = _make_session_factory(get_main_engine())
MetaSessionFactory = _make_session_factory(get_meta_engine())


# ── FastAPI dependency helpers ────────────────────────────────────────────────

async def get_main_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency: yields an AsyncSession for the main (production) DB."""
    async with MainSessionFactory() as session:
        yield session


async def get_meta_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency: yields an AsyncSession for the metadata DB (audit trail)."""
    async with MetaSessionFactory() as session:
        yield session


async def get_backup_db(
    backup_db_name: str | None = None,
) -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency factory: yields an AsyncSession for the backup DB.

    Usage in a route:
        async def my_route(
            backup_db_name: str | None = None,
            backup_session: AsyncSession = Depends(lambda: get_backup_db(backup_db_name))
        ): ...

    Because FastAPI can't directly pass runtime params into Depends,
    we use the helper below instead — see deps.py.
    """
    engine = get_backup_engine(backup_db_name)
    factory = _make_session_factory(engine)
    async with factory() as session:
        yield session


# ── Startup / shutdown ────────────────────────────────────────────────────────

async def dispose_all_engines() -> None:
    """Call on src shutdown to cleanly close all connection pools."""
    for engine in _get_engine.cache_info() and []:   # type: ignore[attr-defined]
        await engine.dispose()

    # Dispose the known fixed engines
    await get_main_engine().dispose()
    await get_meta_engine().dispose()
    logger.info("All DB engines disposed.")