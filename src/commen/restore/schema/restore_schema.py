"""
src/models/schemas.py
Pydantic v2 schemas for request / response validation.
"""

from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field, field_validator, model_validator


class OkResponse(BaseModel):
    detail: str


class BackupLogSchema(BaseModel):
    id:             int
    filename:       str
    local_path:     str | None = None
    s3_key:         str | None = None
    s3_bucket:      str | None = None
    size_bytes:     int | None = None
    size_mb:        float | None = None
    storage:        str
    status:         str
    error_message:  str | None = None
    notes:          str = ""
    backup_db_name: str | None = None
    created_by:     str | None = None
    created_at:     datetime
    completed_at:   datetime | None = None

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def compute_size_mb(cls, values):
        size = getattr(values, "size_bytes", None)
        if size is None and isinstance(values, dict):
            size = values.get("size_bytes")
        if isinstance(values, dict) and "size_mb" not in values:
            values["size_mb"] = round(size / (1024 * 1024), 2) if size else None
        return values


class OrderedRestoreRequest(BaseModel):
    """
    Input for POST /restore/ordered

    tables         : ordered list of PostgreSQL table names (FK parents first).
    backup_db_name : name of the backup PostgreSQL database (optional).
    backup_log_id  : use a specific BackupLog's snapshots (optional).
    dry_run        : if true, only detect — do NOT restore.
    """

    tables: list[str] = Field(
        ...,
        description=(
            "Ordered PostgreSQL table names. FK parents before children. "
            "E.g. ['vouchers_voucher', 'account_user', 'vouchers_studentvoucher']"
        ),
    )
    backup_db_name: str | None = Field(
        default=None,
        description=(
            "Name of the backup PostgreSQL database. "
            "If omitted, uses the default backup DB from settings."
        ),
    )
    backup_log_id: int | None = Field(
        default=None,
        description="ID of a specific BackupLog. Defaults to latest.",
    )
    notes: str = Field(
        default="",
        description="Optional note saved to the audit trail.",
    )
    dry_run: bool = Field(
        default=False,
        description="If true, only detect missing records without restoring.",
    )

    @field_validator("tables")
    @classmethod
    def validate_tables(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("tables list must contain at least one table name.")
        cleaned = [t.strip() for t in v]
        if any(not t for t in cleaned):
            raise ValueError("table names cannot be empty strings.")
        return cleaned


class TableRestoreResult(BaseModel):
    table:        str
    missing_ids:  list[int] = Field(default_factory=list)
    restored_ids: list[int] = Field(default_factory=list)
    failed_ids:   list[int] = Field(default_factory=list)
    errors:       dict[str, str] = Field(default_factory=dict)


class OrderedRestoreResponse(BaseModel):
    backup_db_used:   str
    backup_log_id:    int | None = None
    dry_run:          bool = False
    tables_processed: list[TableRestoreResult] = Field(default_factory=list)
    total_missing:    int = 0
    total_restored:   int = 0
    total_failed:     int = 0


class DetectMissingRequest(BaseModel):
    tables: list[str] = Field(
        ...,
        description="List of PostgreSQL table names to scan.",
    )
    backup_db_name: str | None = None
    backup_log_id:  int | None = None

    @field_validator("tables")
    @classmethod
    def validate_tables(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("tables list must contain at least one table name.")
        cleaned = [t.strip() for t in v]
        if any(not t for t in cleaned):
            raise ValueError("table names cannot be empty strings.")
        return cleaned


class MissingRecord(BaseModel):
    table:     str
    object_id: int
    data:      dict[str, Any] = Field(default_factory=dict)


class DetectMissingResponse(BaseModel):
    backup_db_used: str
    backup_log_id:  int | None = None
    missing:        list[MissingRecord] = Field(default_factory=list)
    total_missing:  int = 0


class RevertLogSchema(BaseModel):
    id:            int
    backup_log_id: int | None = None
    table_name:    str
    object_id:     int
    reverted_by:   str | None = None
    reverted_at:   datetime
    success:       bool
    error_message: str | None = None
    notes:         str = ""

    model_config = {"from_attributes": True}
