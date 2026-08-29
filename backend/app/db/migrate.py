from pathlib import Path

from alembic import command
from alembic.config import Config

from backend.app.core.config import settings


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def alembic_config() -> Config:
    return Config(str(PROJECT_ROOT / "alembic.ini"))


def alembic_config_for_database_url(database_url: str) -> Config:
    config = alembic_config()
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def migrate_to_head(database_url: str) -> None:
    command.upgrade(alembic_config_for_database_url(database_url), "head")


def main() -> None:
    migrate_to_head(settings.database_url)


if __name__ == "__main__":
    main()
