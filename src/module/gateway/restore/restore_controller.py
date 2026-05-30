import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.database import get_main_db, get_meta_db, get_backup_engine
from src.commen.settings import get_settings
from src.commen.restore.schema.restore_schema import (
    DetectMissingRequest,
    DetectMissingResponse,
    OrderedRestoreRequest,
    OrderedRestoreResponse,
)
from src.module.restore.restore_service import RestoreService


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/restore", tags=["Restore"])
settings = get_settings()


@router.post(
    "/ordered",
    response_model=OrderedRestoreResponse,
    summary="Restore deleted records in FK-dependency order",
    description="""
        Finds records that exist in the **backup DB** but are **missing** from the **main DB**,
        then restores them **in the order you specify** (so FK parents are created before children).

        ### How it works
        1. For each table in `tables` (processed in order):
           - Collects all IDs from the backup DB for that table
           - Collects all IDs from the main DB for that table
           - `missing = backup_ids − main_ids`
        2. Fetches the full row from the backup DB for each missing ID
        3. Upserts it into the main DB (`INSERT … ON CONFLICT (id) DO UPDATE`)
        4. Writes an audit entry to the RevertLog

        ### Example — StudentVoucher with FK dependencies
        ```json
        {
          "tables": ["account_user", "courseSaleSystem_studentvoucher"],
          "backup_db_name": "lms_backup_2024_01",
          "notes": "Restoring accidentally deleted records"
        }
        ```

        > ⚠️ **Order matters**: always list FK parents before children.
    """,
    status_code=status.HTTP_200_OK,
)
async def ordered_restore_endpoint(
        body: OrderedRestoreRequest,
        main_session: AsyncSession = Depends(get_main_db),
        meta_session: AsyncSession = Depends(get_meta_db),
) -> OrderedRestoreResponse:
    # Build the backup DSN / meta_session inline so we use body.backup_db_name
    backup_db_name = body.backup_db_name
    engine = get_backup_engine(backup_db_name)

    from sqlalchemy.ext.asyncio import async_sessionmaker
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    try:
        async with factory() as backup_session:
            result = await RestoreService().ordered_restore(
                tables=body.tables,
                main_session=main_session,
                backup_session=backup_session,
                meta_session=meta_session,
                backup_db_name=backup_db_name,
                backup_log_id=body.backup_log_id,
                notes=body.notes,
                performed_by=None,  # extend: pass auth user here
                dry_run=body.dry_run,
            )
    except Exception as exc:
        logger.exception("ordered_restore failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Restore failed: {exc}",
        )

    return result


@router.post(
    "/detect-missing",
    response_model=DetectMissingResponse,
    summary="Detect records missing from main DB (read-only)",
    description="""
        **Safe, read-only** endpoint. Scans the backup DB and returns all records
        that are missing from the main DB — including the **full row data** as preview.

        Use this before `/restore/ordered` to see exactly what would be restored.
    """,
    status_code=status.HTTP_200_OK,
)
async def detect_missing_endpoint(
        body: DetectMissingRequest,
        main_session: AsyncSession = Depends(get_main_db),
        meta_session: AsyncSession = Depends(get_meta_db),
) -> DetectMissingResponse:
    backup_db_name = body.backup_db_name
    engine = get_backup_engine(body.backup_db_name)

    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    try:
        async with factory() as backup_session:
            result = await RestoreService().detect_missing(
                tables=body.tables,
                main_session=main_session,
                backup_session=backup_session,
                meta_session=meta_session,
                backup_db_name=backup_db_name,
                backup_log_id=body.backup_log_id,
            )
    except Exception as exc:
        logger.exception("detect_missing failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Detection failed: {exc}",
        )

    return result
