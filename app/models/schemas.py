from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


# ── Shared ────────────────────────────────────────────────────────────────────

class OkResponse(BaseModel):
    detail: str


# ── Backup Log ────────────────────────────────────────────────────────────────

class BackupLogSchema(BaseModel):
    id:             int
    filename:       str
    local_path:     str | None
    s3_key:         str | None
    s3_bucket:      str | None
    size_bytes:     int | None
    size_mb:        float | None
    storage:        str
    status:         str
    error_message:  str | None
    notes:          str
    backup_db_name: str | None
    created_by:     str | None
    created_at:     datetime
    completed_at:   datetime | None

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def compute_size_mb(cls, values):
        # works for both dict and ORM object
        size = getattr(values, "size_bytes", None) or (
            values.get("size_bytes") if isinstance(values, dict) else None
        )
        if isinstance(values, dict):
            values["size_mb"] = round(size / (1024 * 1024), 2) if size else None
        return values


class OrderedRestoreRequest(BaseModel):
    """
    Input for POST /restore/ordered

    tables: ordered list of PostgreSQL table names.
            FK parents MUST come before children.
            Example: ["vouchers_voucher", "account_user", "vouchers_studentvoucher"]

    backup_db_name: optional — if given, connects to this DB on the backup host.
                    if None   — uses the latest completed backup DB from settings.

    backup_log_id:  optional — use a specific BackupLog's snapshots (faster, no live backup needed).
                    if None   — queries the live backup DB directly.

    dry_run: if true → only detect missing records, do NOT restore.
    """
    tables: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "Ordered PostgreSQL table names. "
            "FK parents before children. "
            "E.g. ['vouchers_voucher', 'account_user', 'vouchers_studentvoucher']"
        ),
        examples=[["vouchers_voucher", "account_user", "vouchers_studentvoucher"]],
    )
    backup_db_name: str  = Field(
        description=(
            "Name of the backup PostgreSQL database. "
            "If omitted, uses the default backup DB from settings."
        ),
    )
    backup_log_id: int | None = Field(
        default=None,
        description="ID of a BackupLog to use for JSON snapshots. Defaults to latest.",
    )
    notes: str = Field(default="", description="Optional note saved to the audit trail.")
    dry_run: bool = Field(
        default=False,
        description="If true, only detect missing records without restoring.",
    )


class TableRestoreResult(BaseModel):
    table:        str
    missing_ids:  list[int]
    restored_ids: list[int]
    failed_ids:   list[int]
    errors:       dict[str, str]   # str(id) → error message


class OrderedRestoreResponse(BaseModel):
    backup_db_used:   str
    backup_log_id:    int | None
    dry_run:          bool
    tables_processed: list[TableRestoreResult]
    total_missing:    int
    total_restored:   int
    total_failed:     int


class DetectMissingRequest(BaseModel):
    tables: list[str]  = Field(..., min_length=1)
    backup_db_name: str
    backup_log_id:  int | None = None


class MissingRecord(BaseModel):
    table:     str
    object_id: int
    data:      dict[str, Any]   # full row from backup


class DetectMissingResponse(BaseModel):
    backup_db_used: str | None
    backup_log_id:  int | None
    missing:        list[MissingRecord]
    total_missing:  int


# ── Revert Log ────────────────────────────────────────────────────────────────

class RevertLogSchema(BaseModel):
    id:            int
    backup_log_id: int | None
    table_name:    str
    object_id:     int
    reverted_by:   str | None
    reverted_at:   datetime
    success:       bool
    error_message: str | None
    notes:         str

    model_config = {"from_attributes": True}