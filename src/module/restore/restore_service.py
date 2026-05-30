"""
src/services/restore_service.py

Core async restore logic:

1. connect to backup DB (dynamic name or default)
2. per table: find IDs in backup but NOT in main  →  missing
3. fetch full row data from backup for each missing ID
4. insert those rows into the main DB
5. write RevertLog audit entries to the meta DB
6. return structured results

Uses raw SQL (via asyncpg through SQLAlchemy text()) so it works with
ANY table — no Django ORM, no model registration needed.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.module.restore.schema import RestoreResultSchema
from src.models.meta_models import BackupLog, RevertLog
from src.commen.restore.schema.restore_schema import (
    DetectMissingResponse,
    MissingRecord,
    OrderedRestoreResponse,
    TableRestoreResult,
)

logger = logging.getLogger(__name__)


class RestoreService:

    async def _get_all_ids(self, session: AsyncSession, table: str) -> set[int]:
        """Return all primary key values (column: id) for a table."""
        result = await session.execute(text(f'SELECT id FROM "{table}"'))
        return {row[0] for row in result.fetchall()}

    async def _fetch_row(self, session: AsyncSession, table: str, pk: int) -> dict | None:
        """Fetch a single row by id, returned as a plain dict."""
        result = await session.execute(
            text(f'SELECT * FROM "{table}" WHERE id = :pk'),
            {"pk": pk},
        )
        row = result.mappings().first()
        return dict(row) if row else None

    async def _table_exists(self, session: AsyncSession, table: str) -> bool:
        """Check if a table exists in the connected DB."""
        result = await session.execute(
            text(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.tables"
                "  WHERE table_schema = 'public' AND table_name = :table"
                ")"
            ),
            {"table": table},
        )
        return bool(result.scalar())

    async def _get_columns(self, session: AsyncSession, table: str) -> list[str]:
        """Return column names for a table."""
        result = await session.execute(
            text(
                "SELECT column_name FROM information_schema.columns"
                " WHERE table_schema = 'public' AND table_name = :table"
                " ORDER BY ordinal_position"
            ),
            {"table": table},
        )
        return [row[0] for row in result.fetchall()]

    async def _upsert_row(
            self,
            session: AsyncSession,
            table: str,
            row: dict,
            columns: list[str],
    ) -> None:
        """
        INSERT the row into main DB.
        If a row with the same id already exists, UPDATE all columns.
        Uses PostgreSQL ON CONFLICT (id) DO UPDATE.
        """
        # Filter row to only known columns (safety)
        safe_row = {k: v for k, v in row.items() if k in columns}
        cols = list(safe_row.keys())

        col_list = ", ".join(f'"{c}"' for c in cols)
        param_list = ", ".join(f":{c}" for c in cols)
        update_list = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in cols if c != "id")

        sql = (
            f'INSERT INTO "{table}" ({col_list}) VALUES ({param_list})'
            f' ON CONFLICT (id) DO UPDATE SET {update_list}'
        )
        await session.execute(text(sql), safe_row)

    # ── Backup log resolution ─────────────────────────────────────────────────────

    async def _resolve_backup_log(
            self,
            meta_session: AsyncSession,
            backup_log_id: int | None,
    ) -> BackupLog | None:
        """Return the requested BackupLog, or the latest completed one."""
        from sqlalchemy import select

        if backup_log_id:
            result = await meta_session.execute(
                select(BackupLog).where(
                    BackupLog.id == backup_log_id,
                    BackupLog.status == "completed",
                )
            )
            return result.scalar_one_or_none()

        result = await meta_session.execute(
            select(BackupLog)
            .where(BackupLog.status == "completed")
            .order_by(BackupLog.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def ordered_restore(
            self,
            tables: list[str],
            main_session: AsyncSession,
            backup_session: AsyncSession,
            meta_session: AsyncSession,
            backup_db_name: str,
            backup_log_id: int | None = None,
            notes: str = "",
            performed_by: str | None = None,
            dry_run: bool = False,
    ) -> OrderedRestoreResponse:
        """
        For each table (IN ORDER):
          1. Find IDs present in backup but missing from main
          2. Fetch the full row from backup
          3. Upsert into main DB
          4. Write RevertLog entry

        Returns a full structured report.
        """
        backup_log = await self._resolve_backup_log(meta_session, backup_log_id)
        results: list[RestoreResultSchema] = []

        for table in tables:
            result = await self._process_table(
                table=table,
                main_session=main_session,
                backup_session=backup_session,
                meta_session=meta_session,
                backup_log=backup_log,
                notes=notes,
                performed_by=performed_by,
                dry_run=dry_run,
            )
            results.append(result)

        total_missing = sum(len(r.missing_ids) for r in results)
        total_restored = sum(len(r.restored_ids) for r in results)
        total_failed = sum(len(r.failed_ids) for r in results)

        return OrderedRestoreResponse(
            backup_db_used=backup_db_name,
            backup_log_id=backup_log.id if backup_log else None,
            dry_run=dry_run,
            tables_processed=[
                TableRestoreResult(
                    table=r.table,
                    missing_ids=r.missing_ids,
                    restored_ids=r.restored_ids,
                    failed_ids=r.failed_ids,
                    errors=r.errors,
                )
                for r in results
            ],
            total_missing=total_missing,
            total_restored=total_restored,
            total_failed=total_failed,
        )

    async def _process_table(
            self,
            table: str,
            main_session: AsyncSession,
            backup_session: AsyncSession,
            meta_session: AsyncSession,
            backup_log: BackupLog | None,
            notes: str,
            performed_by: str | None,
            dry_run: bool,
    ) -> RestoreResultSchema:
        result = RestoreResultSchema(table=table)

        # ── Validate table exists in both DBs ──────────────────────────────────
        if not await self._table_exists(backup_session, table):
            msg = f"Table '{table}' does not exist in the backup DB."
            logger.error(msg)
            result.errors["-1"] = msg
            return result

        if not await self._table_exists(main_session, table):
            msg = f"Table '{table}' does not exist in the main DB."
            logger.error(msg)
            result.errors["-1"] = msg
            return result

        # ── Find missing IDs ────────────────────────────────────────────────────
        backup_ids = await self._get_all_ids(backup_session, table)
        main_ids = await self._get_all_ids(main_session, table)
        missing = sorted(backup_ids - main_ids)
        result.missing_ids = missing

        logger.info(
            "[%s] backup=%d  main=%d  missing=%d",
            table, len(backup_ids), len(main_ids), len(missing),
        )

        if not missing or dry_run:
            if dry_run and missing:
                logger.info("[%s] dry_run=True — skipping restore of %d records.", table, len(missing))
            return result

        # ── Get column list once ────────────────────────────────────────────────
        columns = await self._get_columns(main_session, table)

        # ── Restore each missing row ────────────────────────────────────────────
        for pk in missing:
            row = await self._fetch_row(backup_session, table, pk)
            if row is None:
                result.failed_ids.append(pk)
                result.errors[str(pk)] = "Row not found in backup DB (may have been deleted after backup)."
                continue

            try:
                await self._upsert_row(main_session, table, row, columns)
                await main_session.flush()  # send to DB but keep in transaction

                # audit trail
                await self._write_revert_log(
                    meta_session=meta_session,
                    backup_log=backup_log,
                    table=table,
                    pk=pk,
                    row=row,
                    performed_by=performed_by,
                    notes=notes,
                    success=True,
                )

                result.restored_ids.append(pk)
                logger.info("  ✓ Restored %s #%d", table, pk)

            except Exception as exc:
                error_msg = str(exc)
                result.failed_ids.append(pk)
                result.errors[str(pk)] = error_msg
                logger.error("  ✗ Failed %s #%d: %s", table, pk, error_msg)

                await self._write_revert_log(
                    meta_session=meta_session,
                    backup_log=backup_log,
                    table=table,
                    pk=pk,
                    row=row,
                    performed_by=performed_by,
                    notes=notes,
                    success=False,
                    error=error_msg,
                )

        # Commit all restored rows for this table atomically
        if result.restored_ids:
            await main_session.commit()
            logger.info("[%s] Committed %d rows.", table, len(result.restored_ids))

        return result

    async def _write_revert_log(
            self,
            meta_session: AsyncSession,
            backup_log: BackupLog | None,
            table: str,
            pk: int,
            row: dict,
            performed_by: str | None,
            notes: str,
            success: bool,
            error: str = "",
    ) -> None:
        """Best-effort audit write — never raises."""
        try:
            log = RevertLog(
                backup_log_id=backup_log.id if backup_log else None,
                table_name=table,
                object_id=pk,
                reverted_by=performed_by,
                reverted_at=datetime.now(tz=timezone.utc),
                success=success,
                error_message=error or None,
                notes=notes,
                restored_data=self._serialize_row(row),
            )
            meta_session.add(log)
            await meta_session.flush()
        except Exception as exc:
            logger.warning("Could not write RevertLog: %s", exc)

    def _serialize_row(self, row: dict) -> dict:
        """Make a row JSON-serializable (convert datetime, etc.)."""
        out = {}
        for k, v in row.items():
            if isinstance(v, datetime):
                out[k] = v.isoformat()
            else:
                out[k] = v
        return out

    async def detect_missing(
            self,
            tables: list[str],
            main_session: AsyncSession,
            backup_session: AsyncSession,
            meta_session: AsyncSession,
            backup_db_name: str = f'backup_db_{datetime.now().date()}',
            backup_db_user: str = '',
            backup_log_id: int | None = None,
    ) -> DetectMissingResponse:
        """
        Read-only scan: find records in backup but missing in main.
        Returns full row data for preview.
        """
        backup_log = await self._resolve_backup_log(meta_session, backup_log_id)
        missing_records: list[MissingRecord] = []

        for table in tables:
            if not await self._table_exists(backup_session, table):
                logger.warning("Table '%s' not in backup DB — skipping.", table)
                continue
            if not await self._table_exists(main_session, table):
                logger.warning("Table '%s' not in main DB — skipping.", table)
                continue

            backup_ids = await self._get_all_ids(backup_session, table)
            main_ids = await self._get_all_ids(main_session, table)
            missing = sorted(backup_ids - main_ids)

            for pk in missing:
                row = await self._fetch_row(backup_session, table, pk)
                if row:
                    missing_records.append(
                        MissingRecord(
                            table=table,
                            object_id=pk,
                            data=self._serialize_row(row),
                        )
                    )

        return DetectMissingResponse(
            backup_db_used=backup_db_name,
            backup_log_id=backup_log.id if backup_log else None,
            missing=missing_records,
            total_missing=len(missing_records),
        )
