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

from commen.backup.schema.backup_schema import DeleteBackupSchema
from src.commen.settings import get_settings
from src.models.meta_models import BackupLog
from src.commen.utils.timestamp import DatetimeUtil


logger = logging.getLogger(__name__)
settings = get_settings()


class BackupService:
    def __init__(self, meta_session: AsyncSession):
        self.meta_session = meta_session

    @staticmethod
    def _now_tag() -> str:
        return DatetimeUtil.utc_now_datetime_str()

    @staticmethod
    def _dump_dir() -> Path:
        path = Path(settings.BACKUP_DUMP_DIR)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _pg_main_env() -> dict:
        """
        Build environment variables for pg_dump / pg_restore on the MAIN DB.
        Using PGPASSWORD avoids interactive password prompts.
        """
        env = os.environ.copy()
        env["PGPASSWORD"] = settings.MAIN_DB_PASSWORD
        return env

    @staticmethod
    def _pg_backup_env() -> dict:
        """Environment for pg_restore targeting the BACKUP host."""
        env = os.environ.copy()
        env["PGPASSWORD"] = settings.default_backup_db_password
        return env

    async def _create_backup_database(self, db_name: str) -> None:
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

    def _run_pg_dump(self, dump_path: Path) -> None:
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
        result = subprocess.run(cmd, capture_output=True, env=self._pg_main_env())
        if result.returncode != 0:
            raise RuntimeError(
                f"pg_dump failed (exit {result.returncode}):\n"
                f"STDERR: {result.stderr.decode()}"
            )
        logger.info("pg_dump completed → %s", dump_path)

    def _run_pg_restore(self, dump_path: Path, target_db: str) -> None:
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
        result = subprocess.run(cmd, capture_output=True, env=self._pg_backup_env())
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

    async def _save_backup_log(
        self,
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
        self.meta_session.add(log)
        await self.meta_session.commit()
        await self.meta_session.refresh(log)
        logger.info("BackupLog #%d saved (status=%s).", log.id, status)
        return log

    async def create_backup(
            self,
            notes: str = "",
            created_by: str | None = None,
    ) -> BackupLog:
        tag = self._now_tag()
        db_name = f"backup_db_{tag}"
        filename = f"{db_name}.dump"
        dump_path = self._dump_dir() / filename

        logger.info("=== Starting backup: %s ===", db_name)

        # ── 1. Create backup database ─────────────────────────────────────────────
        try:
            await self._create_backup_database(db_name)
        except Exception as exc:
            error_msg = f"Failed to create backup database '{db_name}': {exc}"
            logger.error(error_msg)
            return await self._save_backup_log(
                db_name, dump_path,
                status="failed", error=error_msg, notes=notes, created_by=created_by,
            )

        # ── 2. pg_dump main DB ────────────────────────────────────────────────────
        try:
            await asyncio.to_thread(self._run_pg_dump, dump_path)
        except Exception as exc:
            error_msg = f"pg_dump failed: {exc}"
            logger.error(error_msg)
            return await self._save_backup_log(
                db_name, dump_path,
                status="failed", error=error_msg, notes=notes, created_by=created_by,
            )

        # ── 3. pg_restore into new backup DB ─────────────────────────────────────
        try:
            await asyncio.to_thread(self._run_pg_restore, dump_path, db_name)
        except Exception as exc:
            error_msg = f"pg_restore failed: {exc}"
            logger.error(error_msg)
            return await self._save_backup_log(
                db_name, dump_path,
                status="failed", error=error_msg, notes=notes, created_by=created_by,
            )

        # ── 4. Save successful BackupLog ──────────────────────────────────────────
        log = await self._save_backup_log(
            db_name, dump_path,
            status="completed", notes=notes, created_by=created_by,
        )

        logger.info(
            "=== Backup complete: %s | size=%.2f MB | dump=%s ===",
            db_name,
            (log.size_bytes or 0) / (1024 * 1024),
            dump_path,
        )
        return log

    def _delete_dump_file(self, local_path: str | None) -> bool:
        """
        Delete the .dump file from disk (BACKUP_DUMP_DIR).
        Returns True if deleted, False if already missing.
        """
        if not local_path:
            logger.warning("No local_path recorded for this backup — skipping file delete.")
            return False

        path = Path(local_path)
        if not path.exists():
            logger.warning("Dump file not found on disk: %s — skipping.", local_path)
            return False

        path.unlink()
        logger.info("Deleted dump file: %s", local_path)
        return True

    async def delete_backup(
            self,
            backup_id: int,
    ) -> DeleteBackupSchema:
        """
        Delete workflow:
          1. Load BackupLog by ID
          2. Delete .dump file from BACKUP_DUMP_DIR
          3. Delete BackupLog + RevertLogs from meta DB

        Raises ValueError if BackupLog not found.
        """

        # ── Load BackupLog ────────────────────────────────────────────────────────
        log: BackupLog | None = await self.meta_session.get(BackupLog, backup_id)
        if not log:
            raise ValueError(f"BackupLog #{backup_id} not found.")

        result = DeleteBackupSchema(
            backup_id=backup_id,
            dump_file=log.local_path,
            db_name=log.filename
        )

        # ── Step 1: Delete dump file ──────────────────────────────────────────────
        try:
            result.dump_deleted = self._delete_dump_file(log.local_path)
        except Exception as exc:
            msg = f"Failed to delete dump file '{log.local_path}': {exc}"
            logger.error(msg)
            result.errors.append(msg)

        # ── Step 2: Delete BackupLog from meta DB ─────────────────────────────────
        # Always runs — even if file delete failed, so admin can clean orphaned logs.
        try:
            log.db_dropped = result.dump_deleted
            await self.meta_session.commit()
            result.log_deleted = False
            logger.info("Deleted BackupLog #%d from meta DB.", backup_id)
        except Exception as exc:
            msg = f"Failed to delete BackupLog #{backup_id} from meta DB: {exc}"
            logger.error(msg)
            result.errors.append(msg)

        return result
