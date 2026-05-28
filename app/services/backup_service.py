"""
Backup service — triggered via API call.

Flow:
  1. Generate a new DB name:  backup_db_YYYYMMDD_HHMMSS
  2. Create that database on the backup host (via asyncpg)
  3. Run pg_dump on the main DB  →  .dump file on disk
  4. Run pg_restore into the new backup DB
  5. Save the BackupLog record to the meta DB
  6. Return the result

Requirements (must be installed on the server):
  - pg_dump   (postgresql-client package)
  - pg_restore

All heavy work (pg_dump / pg_restore) is run in a thread pool
so the async event loop is never blocked.
"""

import asyncio
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.meta_models import BackupLog

logger = logging.getLogger(__name__)
settings = get_settings()


# ── helpers ───────────────────────────────────────────────────────────────────

def _now_tag() -> str:
    """Return current datetime as  YYYYMMDD_HHMMSS  (used in DB name & filename)."""
    return datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M")


def _dump_dir() -> Path:
    """Return (and create) the directory where .dump files are stored."""
    path = Path(settings.BACKUP_DUMP_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _pg_main_env() -> dict:
    """
    Build environment variables for pg_dump / pg_restore on the MAIN DB.
    Using PGPASSWORD avoids interactive password prompts.
    """
    env = os.environ.copy()
    env["PGPASSWORD"] = settings.MAIN_DB_PASSWORD
    return env


def _pg_backup_env() -> dict:
    """Environment for pg_restore targeting the BACKUP host."""
    env = os.environ.copy()
    env["PGPASSWORD"] = settings.default_backup_db_password
    return env


# ── step 1: create the new backup database ───────────────────────────────────

async def _create_backup_database(db_name: str) -> None:
    """
    Connect to the backup PostgreSQL server and CREATE DATABASE <db_name>.
    Uses asyncpg directly (not SQLAlchemy) because CREATE DATABASE cannot
    run inside a transaction block.
    """
    # Connect to the 'postgres' maintenance database on the backup host
    conn = await asyncpg.connect(
        host=settings.DEFAUTL_BACKUP_DB_HOST,
        port=settings.DEFAUTL_BACKUP_DB_PORT,
        user=settings.DEFAUTL_BACKUP_DB_USER,
        password=settings.DEFAUTL_BACKUP_DB_PASSWORD,
        database= "postgres",          # maintenance DB — always exists
    )
    try:
        # Check if it already exists (idempotent)
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", db_name
        )
        if exists:
            logger.warning("Database '%s' already exists — skipping CREATE.", db_name)
            return

        await conn.execute(f'CREATE DATABASE "{db_name}"')
        logger.info("Created backup database: %s", db_name)
    finally:
        await conn.close()


# ── step 2: pg_dump (runs in thread pool) ────────────────────────────────────

def _run_pg_dump(dump_path: Path) -> None:
    """
    Blocking call — wrapped with asyncio.to_thread() by the caller.
    Dumps the MAIN database to a custom-format .dump file.
    """
    cmd = [
        "pg_dump",
        "--format=custom", # compressed, supports pg_restore selective restore
        "--no-acl",
        "--no-owner",
        "--host", settings.MAIN_DB_HOST,
        "--port", str(settings.MAIN_DB_PORT),
        "--username", settings.MAIN_DB_USER,
        "--dbname", settings.MAIN_DB_NAME,
        "--file", str(dump_path),
    ]
    result = subprocess.run(cmd, capture_output=True, env=_pg_main_env())
    if result.returncode != 0:
        raise RuntimeError(
            f"pg_dump failed (exit {result.returncode}):\n"
            f"STDERR: {result.stderr.decode()}"
        )
    logger.info("pg_dump completed → %s", dump_path)


# ── step 3: pg_restore (runs in thread pool) ─────────────────────────────────

def _run_pg_restore(dump_path: Path, target_db: str) -> None:
    """
    Blocking call — wrapped with asyncio.to_thread() by the caller.
    Restores the .dump file into the newly created backup database.
    """
    cmd = [
        "pg_restore",
        "--no-acl",
        "--no-owner",
        "--host", settings.default_backup_db_host,
        "--port", str(settings.default_backup_db_port),
        "--username", settings.default_backup_db_user,
        "--dbname", target_db,
        "--verbose",
        str(dump_path),
    ]
    result = subprocess.run(cmd, capture_output=True, env=_pg_backup_env())
    # pg_restore returns non-zero even on minor warnings — check stderr carefully
    if result.returncode != 0:
        stderr = result.stderr.decode()
        # Ignore pure warnings (lines starting with "pg_restore: warning:")
        real_errors = [
            line for line in stderr.splitlines()
            if line.strip() and "warning" not in line.lower()
        ]
        if real_errors:
            raise RuntimeError(
                f"pg_restore failed (exit {result.returncode}):\n"
                + "\n".join(real_errors)
            )
        logger.warning("pg_restore completed with warnings:\n%s", stderr)
    else:
        logger.info("pg_restore completed → database '%s'", target_db)


# ── step 4: save BackupLog to meta DB ────────────────────────────────────────

async def _save_backup_log(
    meta_session: AsyncSession,
    db_name: str,
    dump_path: Path,
    status: str,
    error: str = "",
    notes: str = "",
    created_by: str | None = None,
) -> BackupLog:
    size_bytes = dump_path.stat().st_size if dump_path.exists() else None

    log = BackupLog(
        filename=dump_path.name,
        local_path=str(dump_path),
        size_bytes=size_bytes,
        storage="local",
        status=status,
        error_message=error or None,
        notes=notes,
        backup_db_name=db_name,
        created_by=created_by,
        completed_at=datetime.now(tz=timezone.utc) if status == "completed" else None,
    )
    meta_session.add(log)
    await meta_session.commit()
    await meta_session.refresh(log)
    logger.info("BackupLog #%d saved (status=%s).", log.id, status)
    return log



async def create_backup(
    meta_session: AsyncSession,
    notes: str = "",
    created_by: str | None = None,
) -> BackupLog:
    """
    Full backup workflow (called from the API router):

      1. Generate dated DB name  →  backup_db_YYYYMMDD_HHMMSS
      2. CREATE that database on the backup host
      3. pg_dump  main DB  →  /backups/backup_db_YYYYMMDD_HHMMSS.dump
      4. pg_restore  .dump  →  new backup DB
      5. Write BackupLog to meta DB
      6. Return BackupLog

    Raises on critical failure after writing a 'failed' BackupLog.
    """
    tag = _now_tag()
    db_name = f"backup_db_{tag}"
    filename = f"{db_name}.dump"
    dump_path = _dump_dir() / filename

    logger.info("=== Starting backup: %s ===", db_name)

    # ── 1. Create backup database ─────────────────────────────────────────────
    try:
        await _create_backup_database(db_name)
    except Exception as exc:
        error_msg = f"Failed to create backup database '{db_name}': {exc}"
        logger.error(error_msg)
        return await _save_backup_log(
            meta_session, db_name, dump_path,
            status="failed", error=error_msg, notes=notes, created_by=created_by,
        )

    # ── 2. pg_dump main DB ────────────────────────────────────────────────────
    try:
        await asyncio.to_thread(_run_pg_dump, dump_path)
    except Exception as exc:
        error_msg = f"pg_dump failed: {exc}"
        logger.error(error_msg)
        return await _save_backup_log(
            meta_session, db_name, dump_path,
            status="failed", error=error_msg, notes=notes, created_by=created_by,
        )

    # ── 3. pg_restore into new backup DB ─────────────────────────────────────
    try:
        await asyncio.to_thread(_run_pg_restore, dump_path, db_name)
    except Exception as exc:
        error_msg = f"pg_restore failed: {exc}"
        logger.error(error_msg)
        return await _save_backup_log(
            meta_session, db_name, dump_path,
            status="failed", error=error_msg, notes=notes, created_by=created_by,
        )

    # ── 4. Save successful BackupLog ──────────────────────────────────────────
    log = await _save_backup_log(
        meta_session, db_name, dump_path,
        status="completed", notes=notes, created_by=created_by,
    )

    logger.info(
        "=== Backup complete: %s | size=%.2f MB | dump=%s ===",
        db_name,
        (log.size_bytes or 0) / (1024 * 1024),
        dump_path,
    )
    return log
