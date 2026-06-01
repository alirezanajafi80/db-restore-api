import os
from sqlalchemy import create_engine, text
from alembic.config import Config
from alembic import command

# All the database models must be imported here.
from common.lib.base_entity import BaseEntity

from common.settings import EnvironmentEnum
from common.settings import get_settings
import logging


logger = logging.getLogger(__name__)

current_dir = os.path.dirname(os.path.abspath(__file__))


def get_sync_dsn() -> str:
    """Strip async driver prefix for use with sync SQLAlchemy / Alembic."""
    return get_settings().meta_db_dsn.replace("+asyncpg", "")


def check_if_database_is_empty():
    engine = create_engine(get_sync_dsn(), future=True, echo=True)
    with engine.connect() as conn:
        result = conn.execute(text(f" SELECT  count(distinct table_name) c  FROM information_schema.tables"
                                   f" WHERE table_catalog='{get_settings().META_DB_NAME}' and table_schema='public';"))
        result = result.fetchone()
        return result[0] == 0


def stamp_alembic_head():
    alembic_cfg = Config(os.path.join(current_dir, '../alembic.ini'))
    alembic_cfg.set_main_option('script_location',
                                os.path.join(current_dir, 'migrations'))
    command.stamp(alembic_cfg, "head")


def init_tables():
    engine = create_engine(get_settings().meta_db_dsn, future=True, echo=True)
    BaseEntity.metadata.create_all(engine)
    stamp_alembic_head()


def upgrade_head():
    alembic_cfg = Config(os.path.join(current_dir, '../alembic.ini'))
    alembic_cfg.set_main_option('script_location',
                                os.path.join(current_dir, 'migrations'))
    # ✅ sync URL — بدون +asyncpg
    alembic_cfg.set_main_option(
        'sqlalchemy.url',
        get_settings().meta_db_dsn.replace('+asyncpg', '')
    )
    command.upgrade(alembic_cfg, 'head')


def run_migrations():
    logger.info("Caution: This will try to create tables on a raw database.")
    logger.info("This database will create all tables in raw database and stamps alembic revision to HEAD.")
    if not check_if_database_is_empty():
        logger.info("Database was not empty. So run the latest migrations... ")
    else:
        logger.info("Database was empty.")
        init_tables()
    logger.info("Running migrations ...")
    upgrade_head()
    logger.info("Running migrations Finished.")


if __name__ == '__main__':
    run_migrations()
