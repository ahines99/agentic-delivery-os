from pathlib import Path

from alembic import command
from alembic.config import Config


def migration_config(url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def upgrade(url: str) -> None:
    command.upgrade(migration_config(url), "head")
