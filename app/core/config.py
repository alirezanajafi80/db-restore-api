from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Main DB ──────────────────────────────────────────────────────────────
    main_db_host:     str = "localhost"
    main_db_port:     int = 5432
    main_db_name:     str = ""
    main_db_user:     str = ""
    main_db_password: str = ""

    # ── Default Backup DB ────────────────────────────────────────────────────
    default_backup_db_host:     str = "localhost"
    default_backup_db_port:     int = 5432
    default_backup_db_name:     str = None
    default_backup_db_user:     str = None
    default_backup_db_password: str = None

    # ── Meta DB (audit trail storage) ────────────────────────────────────────
    meta_db_host:     str = "localhost"
    meta_db_port:     int = 5432
    meta_db_name:     str = ""
    meta_db_user:     str = ""
    meta_db_password: str = ""

    # ── AWS ──────────────────────────────────────────────────────────────────
    aws_access_key_id:      str = ""
    aws_secret_access_key:  str = ""
    aws_backup_bucket_name: str = ""
    aws_s3_region_name:     str = "eu-west-1"

    # ── App ──────────────────────────────────────────────────────────────────
    app_env:    str = "development"
    secret_key: str = "change-me"
    log_level:  str = "INFO"

    # ── Computed DSNs ────────────────────────────────────────────────────────
    @property
    def main_db_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.main_db_user}:{self.main_db_password}"
            f"@{self.main_db_host}:{self.main_db_port}/{self.main_db_name}"
        )

    @property
    def default_backup_db_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.default_backup_db_user}:{self.default_backup_db_password}"
            f"@{self.default_backup_db_host}:{self.default_backup_db_port}/{self.default_backup_db_name}"
        )

    @property
    def meta_db_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.meta_db_user}:{self.meta_db_password}"
            f"@{self.meta_db_host}:{self.meta_db_port}/{self.meta_db_name}"
        )

    def build_backup_dsn(self, db_name: str) -> str:
        """
        Build a DSN for an arbitrary backup DB on the same host as the default backup.
        Used when the caller passes a custom backup_db_name.
        """
        return (
            f"postgresql+asyncpg://{self.default_backup_db_user}:{self.default_backup_db_password}"
            f"@{self.default_backup_db_host}:{self.default_backup_db_port}/{db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()

print(get_settings().model_dump())
