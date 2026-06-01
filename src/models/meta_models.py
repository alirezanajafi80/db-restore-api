from datetime import datetime
from typing import Any
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from common.lib.base_entity import BaseEntity


class BackupLogEntity(BaseEntity):
    __tablename__ = "backup_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    local_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    s3_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    s3_bucket: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # "local" | "s3" | "both"
    storage: Mapped[str] = mapped_column(String(10), default="local")
    # "pending" | "in_progress" | "completed" | "failed"
    status: Mapped[str] = mapped_column(String(20), default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")

    backup_db_name: Mapped[str | None] = mapped_column(String(255), nullable=True,
                                                       doc="Which backup DB was used")
    created_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # relationships
    snapshots: Mapped[list["RecordSnapshotEntity"]] = relationship("RecordSnapshotEntity",
                                                                   back_populates="backup_log",
                                                                   cascade="all, delete-orphan")
    revert_logs: Mapped[list["RevertLogEntity"]] = relationship("RevertLogEntity",
                                                                back_populates="backup_log",
                                                                cascade="all, delete-orphan")
    db_dropped: Mapped[bool] = mapped_column(Boolean, default=False)

    @property
    def size_mb(self) -> float | None:
        return round(self.size_bytes / (1024 * 1024), 2) if self.size_bytes else None

class RecordSnapshotEntity(BaseEntity):
    __tablename__ = "record_snapshot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    backup_log_id: Mapped[int] = mapped_column(ForeignKey("backup_log.id", ondelete="CASCADE"))
    model_label: Mapped[str] = mapped_column(String(150))
    object_id: Mapped[int] = mapped_column(Integer)
    data: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    backup_log: Mapped["BackupLogEntity"] = relationship("BackupLogEntity", back_populates="snapshots")


class RevertLogEntity(BaseEntity):
    __tablename__ = "revert_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    backup_log_id: Mapped[int | None] = mapped_column(ForeignKey("backup_log.id",
                                                                  ondelete="SET NULL"), nullable=True)
    table_name: Mapped[str] = mapped_column(String(150))
    object_id: Mapped[int] = mapped_column(Integer)
    reverted_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    reverted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    restored_data: Mapped[Any | None] = mapped_column(JSON, nullable=True)

    backup_log: Mapped["BackupLogEntity | None"] = relationship("BackupLogEntity", back_populates="revert_logs")