"""
src/core/database.py
"""

import logging
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import AsyncGenerator

from sqlalchemy import Column, DateTime, event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker, with_loader_criteria

from common.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

RECYCLE_POOL_IN = 7.5 * 60 * 60

# ── Engines ───────────────────────────────────────────────────────────────────

main_engine = create_async_engine(
    settings.main_db_dsn,
    future=True,
    pool_recycle=RECYCLE_POOL_IN,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_pre_ping=True,
)

meta_engine = create_async_engine(
    settings.meta_db_dsn,
    future=True,
    pool_recycle=RECYCLE_POOL_IN,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_pre_ping=True,
)


@lru_cache(maxsize=32)
def _get_backup_engine(dsn: str):
    """Cached backup engine — one per unique DSN."""
    logger.info("Creating backup engine for: %s", dsn.split("@")[-1])
    return create_async_engine(
        dsn,
        future=True,
        pool_recycle=RECYCLE_POOL_IN,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        pool_pre_ping=True,
    )


# ── Session factories ─────────────────────────────────────────────────────────

MainSessionLocal = sessionmaker(
    bind=main_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)

MetaSessionLocal = sessionmaker(
    bind=meta_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)

# ── Base + mixins ─────────────────────────────────────────────────────────────

Base = declarative_base()


class HasSoftDelete:
    deleted_at = Column(DateTime)


class Dictable:
    def to_dict(self):
        class_vars = vars(self.__class__)
        inst_vars = vars(self)
        all_vars = dict(class_vars)
        all_vars.update(inst_vars)
        return {k: v for k, v in all_vars.items() if not k.startswith("_")}


# ── Soft-delete listener ──────────────────────────────────────────────────────

def add_listener_for_session(session: AsyncSession):
    @event.listens_for(session.sync_session, "do_orm_execute")
    def _add_filtering_criteria(execute_state):
        if (
            not execute_state.is_column_load
            and not execute_state.is_relationship_load
            and not execute_state.execution_options.get("include_deleted", False)
        ):
            execute_state.statement = execute_state.statement.options(
                with_loader_criteria(
                    HasSoftDelete,
                    lambda cls: cls.deleted_at.is_(None),
                    include_aliases=True,
                )
            )


# ── Session context managers ──────────────────────────────────────────────────

@asynccontextmanager
async def get_main_db() -> AsyncGenerator[AsyncSession, None]:
    async with MainSessionLocal() as session:
        add_listener_for_session(session)
        yield session


@asynccontextmanager
async def get_meta_db() -> AsyncGenerator[AsyncSession, None]:
    async with MetaSessionLocal() as session:
        add_listener_for_session(session)
        yield session


@asynccontextmanager
async def get_backup_db(
    backup_db_name: str | None = None,
) -> AsyncGenerator[AsyncSession, None]:
    dsn = (
        settings.build_backup_dsn(backup_db_name)
        if backup_db_name
        else settings.default_backup_db_dsn
    )
    engine = _get_backup_engine(dsn)
    factory = sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )
    async with factory() as session:
        add_listener_for_session(session)
        yield session


async def get_main_db_dep() -> AsyncGenerator[AsyncSession, None]:
    async with get_main_db() as session:
        yield session


async def get_meta_db_dep() -> AsyncGenerator[AsyncSession, None]:
    async with get_meta_db() as session:
        yield session

# ── Shutdown ──────────────────────────────────────────────────────────────────

async def dispose_all_engines() -> None:
    await main_engine.dispose()
    await meta_engine.dispose()
    for dsn in list(_get_backup_engine.cache_parameters()):
        await _get_backup_engine(dsn).dispose()
    logger.info("All DB engines disposed.")