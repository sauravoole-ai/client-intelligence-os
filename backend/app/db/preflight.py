from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from backend.app.db.migrate import alembic_config


class ProductionDatabasePreflightError(RuntimeError):
    pass


def run_production_database_preflight(engine: Engine) -> None:
    try:
        with engine.connect() as connection:
            database_heads = tuple(
                MigrationContext.configure(connection).get_current_heads()
            )
            repository_heads = tuple(
                ScriptDirectory.from_config(alembic_config()).get_heads()
            )
            if (
                len(repository_heads) != 1
                or len(database_heads) != 1
                or repository_heads[0] != database_heads[0]
            ):
                raise ProductionDatabasePreflightError(
                    "Production database migration state is ambiguous or incompatible."
                )

            for table_name in ("clients", "analyses", "action_items"):
                unowned_count = connection.scalar(
                    text(f"SELECT COUNT(*) FROM {table_name} WHERE workspace_id IS NULL")
                )
                if unowned_count:
                    raise ProductionDatabasePreflightError(
                        f"Production database contains unowned {table_name} records."
                    )
    except ProductionDatabasePreflightError:
        raise
    except SQLAlchemyError as error:
        raise ProductionDatabasePreflightError(
            "Production database is unavailable or could not be inspected."
        ) from error
