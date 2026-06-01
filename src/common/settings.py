import os
from enum import Enum
from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENV_FILE = os.path.join(ROOT_DIR, ".env")


class EnvironmentEnum(str, Enum):
    TEST = 'TEST'
    DEVELOPMENT = 'DEVELOPMENT'
    PRODUCTION = 'PRODUCTION'
    BG_TASK = 'BG_TASK'


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Main DB ──────────────────────────────────────────────────────────────
    MAIN_DB_HOST: str = Field("localhost", alias='MAIN_DB_HOST')
    MAIN_DB_PORT: int = Field(5432, alias='MAIN_DB_PORT')
    MAIN_DB_NAME: str = Field(..., alias='MAIN_DB_NAME')
    MAIN_DB_USER: str = Field(..., alias='MAIN_DB_USER')
    MAIN_DB_PASSWORD: str = Field(..., alias='MAIN_DB_PASSWORD')

    #
    DEFAUTL_BACKUP_DB_HOST: str = Field("localhost", alias='DEFAUTL_BACKUP_DB_HOST')
    DEFAUTL_BACKUP_DB_PORT: int = Field(5432, alias='DEFAUTL_BACKUP_DB_PORT')
    DEFAUTL_BACKUP_DB_USER: str = Field(..., alias='DEFAUTL_BACKUP_DB_USER')
    DEFAUTL_BACKUP_DB_PASSWORD: str = Field(..., alias='DEFAUTL_BACKUP_DB_PASSWORD')

    # ── Meta DB (audit trail storage) ────────────────────────────────────────
    META_DB_HOST: str = Field("localhost", alias='META_DB_HOST')
    META_DB_PORT: int = Field(5432, alias='META_DB_PORT')
    META_DB_NAME: str = Field(..., alias='META_DB_NAME')
    META_DB_USER: str = Field(..., alias='META_DB_USER')
    META_DB_PASSWORD: str = Field(..., alias='META_DB_PASSWORD')

    # ── AWS ──────────────────────────────────────────────────────────────────
    AWS_ACCESS_KEY_ID: str = Field(..., alias='AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY:  str = Field(..., alias='AWS_SECRET_ACCESS_KEY')
    AWS_BACKUP_BUCKET_NAME: str = Field(..., alias='AWS_BACKUP_BUCKET_NAME')
    AWS_S3_REGION_NAME: str = Field("eu-west-1", alias='AWS_S3_REGION_NAME')

    # ── App ──────────────────────────────────────────────────────────────────
    ENV: EnvironmentEnum = Field(..., alias='ENV')
    SECRET_KEY: str = "change-me"
    LOG_LEVEL:  str = "INFO"

    # ── Media ──────────────────────────────────────────────────────────────────
    BACKUP_DUMP_DIR: str = Field(..., alias='BACKUP_DUMP_DIR')

    CORS_ALLOW_ORIGINS: List[str] = Field(['*'], alias='CORS_ALLOW_ORIGINS')

    # ── Computed DSNs ────────────────────────────────────────────────────────
    @property
    def main_db_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.MAIN_DB_USER}:{self.MAIN_DB_PASSWORD}"
            f"@{self.MAIN_DB_HOST}:{self.MAIN_DB_PORT}/{self.MAIN_DB_NAME}"
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
            f"postgresql+asyncpg://{self.META_DB_USER}:{self.META_DB_PASSWORD}"
            f"@{self.META_DB_HOST}:{self.META_DB_PORT}/{self.META_DB_NAME}"
        )

    def build_backup_dsn(self, db_name: str) -> str:
        """
        Build a DSN for an arbitrary backup DB on the same host as the default backup.
        Used when the caller passes a custom backup_db_name.
        """
        return (
            f"postgresql+asyncpg://{self.DEFAUTL_BACKUP_DB_USER}:{self.DEFAUTL_BACKUP_DB_PASSWORD}"
            f"@{self.DEFAUTL_BACKUP_DB_HOST}:{self.DEFAUTL_BACKUP_DB_PORT}/{db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
