from datetime import datetime
from pydantic import BaseModel, Field


class CreateBackupRequest(BaseModel):
    notes: str = Field(default="", description="Optional note saved to the BackupLog.")
    created_by: str | None = Field(
        default=None,
        description="Username or identifier of who triggered the backup.",
    )


class CreateBackupResponse(BaseModel):
    id: int
    db_name: str = Field(description="Name of the newly created backup database.")
    dump_file: str = Field(description="Absolute path to the .dump file on disk.")
    size_mb: float | None
    status: str
    error_message: str | None
    notes: str
    created_by: str | None
    created_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}
