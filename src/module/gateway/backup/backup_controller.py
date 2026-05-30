import logging
from pathlib import Path

from src.commen.backup.schema.backup_schema import CreateBackupResponse, CreateBackupRequest, DeleteBackupResultSchema
from src.module.backup.backup_service import BackupService
import os
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import FileResponse, JSONResponse

from src.database import get_meta_db
from src.models.meta_models import BackupLog, RevertLog
from src.commen.restore.schema.restore_schema import BackupLogSchema, OkResponse, RevertLogSchema
import aiofiles.os as aio_os


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/backup", tags=["Backup"])


@router.post(
    "/create",
    response_model=CreateBackupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a full backup of the main database",
    description="""
        Performs a **full backup** of the main production database and stores it as a
        new PostgreSQL database on the backup host.

        ### What happens internally

        | Step | Action |
        |------|--------|
        | 1 | Generate backup DB name: `backup_db_YYYYMMDD_HHMMSS` |
        | 2 | `CREATE DATABASE backup_db_...` on the backup host |
        | 3 | `pg_dump` the main DB → `.dump` file saved to `BACKUP_DUMP_DIR` |
        | 4 | `pg_restore` the dump into the new backup database |
        | 5 | Save a `BackupLog` entry to the meta DB |

        ### Response
        Returns the `BackupLog` record including the new database name and dump file path.

        ### Requirements
        `pg_dump` and `pg_restore` must be installed on the server:
        ```bash
        apt install postgresql-client
        ```

        ### Environment variable
        `BACKUP_DUMP_DIR` — directory where `.dump` files are saved (default: `/backups`)
            """,
)
async def create_backup_endpoint(
        body: CreateBackupRequest = CreateBackupRequest(),
        meta_session: AsyncSession = Depends(get_meta_db),
) -> CreateBackupResponse:
    log = await BackupService(meta_session=meta_session).create_backup(
        notes=body.notes,
        created_by=body.created_by,
    )

    if log.status == "failed":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=log.error_message or "Backup failed for an unknown reason.",
        )

    return CreateBackupResponse(
        id=log.id,
        db_name=log.backup_db_name or "",
        dump_file=log.local_path or "",
        size_mb=log.size_mb,
        status=log.status,
        error_message=log.error_message,
        notes=log.notes,
        created_by=log.created_by,
        created_at=log.created_at,
        completed_at=log.completed_at,
    )


@router.get(
    "/{backup_id}/download",
    summary="Download the .dump file for a backup",
    response_class=FileResponse,
)
async def download_backup(
        backup_id: int,
        session: AsyncSession = Depends(get_meta_db),
) -> FileResponse:
    log = await session.get(BackupLog, backup_id)
    if not log:
        raise HTTPException(status_code=404, detail="BackupLog not found.")

    if not log.local_path:
        raise HTTPException(
            status_code=404,
            detail="No local dump file path recorded for this backup.",
        )

    if not os.path.exists(log.local_path):
        raise HTTPException(
            status_code=404,
            detail=f"Dump file not found on disk: {log.local_path}",
        )

    return FileResponse(
        path=log.local_path,
        filename=log.filename,
        media_type="application/octet-stream",
    )

@router.get(
    "/",
    response_model=list[BackupLogSchema],
    summary="List all backup log entries",
)
async def list_backups(
        session: AsyncSession = Depends(get_meta_db),
) -> list[BackupLogSchema]:
    result = await session.execute(
        select(BackupLog).order_by(BackupLog.created_at.desc())
    )
    logs = result.scalars().all()
    return [BackupLogSchema.model_validate(log) for log in logs]


@router.get(
    "/{backup_id}",
    response_model=BackupLogSchema,
    summary="Get a single backup log entry",
)
async def get_backup(
        backup_id: int,
        session: AsyncSession = Depends(get_meta_db),
) -> BackupLogSchema:
    log = await session.get(BackupLog, backup_id)
    if not log:
        raise HTTPException(status_code=404, detail="BackupLog not found.")
    return BackupLogSchema.model_validate(log)


@router.delete(
    "log/{backup_id}",
    response_model=OkResponse,
    summary="Delete a backup log entry and its audit records",
)
async def delete_backup_log(
        backup_id: int,
        session: AsyncSession = Depends(get_meta_db),
) -> OkResponse:
    log = await session.get(BackupLog, backup_id)
    if not log:
        raise HTTPException(status_code=404, detail="BackupLog not found.")

    # db_path = await log.local_path
    # if db_path:
    #     path = Path(db_path)
    #     if await aio_os.path.exists(str(path)):
    #         try:
    #             await aio_os.remove(str(path))
    #             logger.info(f"Deleted file: {db_path}")
    #         except Exception as e:
    #             logger.error(f"Failed to delete {db_path}: {e}")

    await session.delete(log)
    await session.commit()
    return OkResponse(detail=f"BackupLog #{backup_id} deleted.")


@router.get(
    "/revert-logs/all",
    response_model=list[RevertLogSchema],
    summary="List all revert (restore) audit entries",
)
async def list_revert_logs(
        session: AsyncSession = Depends(get_meta_db),
) -> list[RevertLogSchema]:
    result = await session.execute(
        select(RevertLog).order_by(RevertLog.reverted_at.desc())
    )
    logs = result.scalars().all()
    return [RevertLogSchema.model_validate(log) for log in logs]


@router.get(
    "/{backup_id}/revert-logs",
    response_model=list[RevertLogSchema],
    summary="List revert logs for a specific backup",
)
async def list_revert_logs_for_backup(
        backup_id: int,
        session: AsyncSession = Depends(get_meta_db),
) -> list[RevertLogSchema]:
    result = await session.execute(
        select(RevertLog)
        .where(RevertLog.backup_log_id == backup_id)
        .order_by(RevertLog.reverted_at.desc())
    )
    logs = result.scalars().all()
    return [RevertLogSchema.model_validate(log) for log in logs]


@router.delete(
    "/delete/dump/file/{backup_id}",
    response_model=DeleteBackupResultSchema,
    summary="Delete backup dump file from disk and remove its log",
)
async def delete_backup_endpoint(
        backup_id: int,
        meta_session: AsyncSession = Depends(get_meta_db),
):
    try:
        result = await BackupService(meta_session=meta_session).delete_backup(
            backup_id=backup_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Delete failed: {exc}",
        )

    http_status = status.HTTP_200_OK if result.success else status.HTTP_207_MULTI_STATUS

    return JSONResponse(
        status_code=http_status,
        content=DeleteBackupResultSchema(
            backup_id=result.backup_id,
            db_name=result.db_name,
            dump_file=result.dump_file,
            log_deleted=result.log_deleted,
            errors=result.errors
        ).model_dump(),
    )



