import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_meta_db
from app.models.schemas import BackupLogSchema
from app.services.backup_service import create_backup

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/backup", tags=["Backup"])



class CreateBackupRequest(BaseModel):
    notes:      str = Field(default="", description="Optional note saved to the BackupLog.")
    created_by: str | None = Field(
        default=None,
        description="Username or identifier of who triggered the backup.",
    )


class CreateBackupResponse(BaseModel):
    id:             int
    db_name:        str = Field(description="Name of the newly created backup database.")
    dump_file:      str = Field(description="Absolute path to the .dump file on disk.")
    size_mb:        float | None
    status:         str
    error_message:  str | None
    notes:          str
    created_by:     str | None
    created_at:     datetime
    completed_at:   datetime | None

    model_config = {"from_attributes": True}


# ── Route ─────────────────────────────────────────────────────────────────────

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
    body:         CreateBackupRequest = CreateBackupRequest(),
    meta_session: AsyncSession        = Depends(get_meta_db),
) -> CreateBackupResponse:

    log = await create_backup(
        meta_session = meta_session,
        notes        = body.notes,
        created_by   = body.created_by,
    )

    if log.status == "failed":
        # Still return 201 body but with failed status so the caller sees the error
        # Raise 500 instead if you prefer an error HTTP code on failure:
        raise HTTPException(
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail      = log.error_message or "Backup failed for an unknown reason.",
        )

    return CreateBackupResponse(
        id            = log.id,
        db_name       = log.backup_db_name or "",
        dump_file     = log.local_path or "",
        size_mb       = log.size_mb,
        status        = log.status,
        error_message = log.error_message,
        notes         = log.notes,
        created_by    = log.created_by,
        created_at    = log.created_at,
        completed_at  = log.completed_at,
    )