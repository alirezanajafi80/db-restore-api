import os
import sys
from dotenv import load_dotenv
from common.settings import EnvironmentEnum, get_settings

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
POSSIBLE_DOTENV_PATH = os.path.join(CURRENT_DIR, '..', '..', '.env')
if os.path.isfile(POSSIBLE_DOTENV_PATH):
    load_dotenv(POSSIBLE_DOTENV_PATH)


def get_migration_connection_string():
    if os.environ.get('ENV') == EnvironmentEnum.TEST:
        db_user = os.environ.get('TEST_DATABASE_USER')
        db_password = os.environ.get('TEST_DATABASE_PASSWORD')
        db_host = os.environ.get('TEST_DATABASE_HOST')
        db_port = os.environ.get('TEST_DATABASE_PORT', 5432)
        db_name = os.environ.get('TEST_DATABASE_NAME')
    else:
        db_user = os.environ.get('DATABASE_USER')
        db_password = os.environ.get('DATABASE_PASSWORD')
        db_host = os.environ.get('DATABASE_HOST')
        db_port = os.environ.get('DATABASE_PORT', 5432)
        db_name = os.environ.get('DATABASE_NAME')
    if not all([db_user, db_password, db_host, db_name, db_port]):
        sys.exit("Please, set the required ENVs before running migrations.")

    return f"postgresql+psycopg2://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"


def get_database_connection_string():
    settings = get_settings()

    if settings.ENV == EnvironmentEnum.TEST:
        return f"postgresql+asyncpg://{settings.TEST_DATABASE_USER}:" \
                                  f"{settings.TEST_DATABASE_PASSWORD}@" \
                                  f"{settings.TEST_DATABASE_HOST}:{settings.TEST_DATABASE_PORT}/{settings.TEST_DATABASE_NAME}"
    else:
        return f"postgresql+asyncpg://{settings.DATABASE_USER}:" \
                                  f"{settings.DATABASE_PASSWORD}@" \
                                  f"{settings.DATABASE_HOST}:{settings.DATABASE_PORT}/{settings.DATABASE_NAME}"