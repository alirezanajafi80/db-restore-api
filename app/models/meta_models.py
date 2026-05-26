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
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class BackupLog(Base):
    """
    Metadata record for each backup operation.
    Mirrors the Django BackupLog model but lives in the meta DB.
    """
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
    snapshots: Mapped[list["RecordSnapshot"]] = relationship("RecordSnapshot",
                                                             back_populates="backup_log",
                                                             cascade="all, delete-orphan")
    revert_logs: Mapped[list["RevertLog"]] = relationship("RevertLog",
                                                          back_populates="backup_log",
                                                          cascade="all, delete-orphan")

    @property
    def size_mb(self) -> float | None:
        return round(self.size_bytes / (1024 * 1024), 2) if self.size_bytes else None


class RecordSnapshot(Base):
    """
    JSON snapshot of a single DB record captured during backup.
    Enables per-item restore without a live backup DB connection.
    """
    __tablename__ = "record_snapshot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    backup_log_id: Mapped[int] = mapped_column(ForeignKey("backup_log.id", ondelete="CASCADE"))
    model_label: Mapped[str] = mapped_column(String(150),
                                             doc="e.g. 'vouchers_studentvoucher'  (table name)")
    object_id: Mapped[int] = mapped_column(Integer)
    data: Mapped[Any] = mapped_column(JSON, doc="Full row as JSON dict")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())

    backup_log: Mapped["BackupLog"] = relationship("BackupLog", back_populates="snapshots")


class RevertLog(Base):
    """
    Audit trail: one row per restored record.
    """
    __tablename__ = "revert_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    backup_log_id: Mapped[int | None] = mapped_column(ForeignKey("backup_log.id",
                                                                 ondelete="SET NULL"), nullable=True)
    table_name: Mapped[str] = mapped_column(String(150))
    object_id: Mapped[int] = mapped_column(Integer)
    reverted_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    reverted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                  server_default=func.now())
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    restored_data: Mapped[Any | None] = mapped_column(JSON, nullable=True,
                                                      doc="Snapshot of what was restored")

    backup_log: Mapped["BackupLog | None"] = relationship("BackupLog", back_populates="revert_logs")
