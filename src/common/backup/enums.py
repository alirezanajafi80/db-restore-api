from enum import Enum


class BackupStatusEnum(str, Enum):
    FAILED = "failed"
    COMPLETED = "completed"