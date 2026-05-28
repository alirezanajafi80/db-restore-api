from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_meta_db
from app.models.meta_models import BackupLog, RevertLog
from app.commen.restore.schema.restore_schema import BackupLogSchema, OkResponse, RevertLogSchema

router = APIRouter(prefix="/backups", tags=["Backup Logs"])


@router.get(
    "/",
    response_model=list[BackupLogSchema],
    summary="List all backup log entries",
)
async def list_backups(
        meta: AsyncSession = Depends(get_meta_db),
) -> list[BackupLogSchema]:
    result = await meta.execute(
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
        meta: AsyncSession = Depends(get_meta_db),
) -> BackupLogSchema:
    log = await meta.get(BackupLog, backup_id)
    if not log:
        raise HTTPException(status_code=404, detail="BackupLog not found.")
    return BackupLogSchema.model_validate(log)


@router.delete(
    "/{backup_id}",
    response_model=OkResponse,
    summary="Delete a backup log entry and its audit records",
)
async def delete_backup_log(
        backup_id: int,
        meta: AsyncSession = Depends(get_meta_db),
) -> OkResponse:
    log = await meta.get(BackupLog, backup_id)
    if not log:
        raise HTTPException(status_code=404, detail="BackupLog not found.")
    await meta.delete(log)
    await meta.commit()
    return OkResponse(detail=f"BackupLog #{backup_id} deleted.")


@router.get(
    "/revert-logs/all",
    response_model=list[RevertLogSchema],
    summary="List all revert (restore) audit entries",
)
async def list_revert_logs(
        meta: AsyncSession = Depends(get_meta_db),
) -> list[RevertLogSchema]:
    result = await meta.execute(
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
        meta: AsyncSession = Depends(get_meta_db),
) -> list[RevertLogSchema]:
    result = await meta.execute(
        select(RevertLog)
        .where(RevertLog.backup_log_id == backup_id)
        .order_by(RevertLog.reverted_at.desc())
    )
    logs = result.scalars().all()
    return [RevertLogSchema.model_validate(log) for log in logs]
