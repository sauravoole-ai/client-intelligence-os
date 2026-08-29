from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import settings
from backend.app.db.base import Base
from backend.app.db.preflight import run_production_database_preflight


def create_database_engine(database_url: str) -> Engine:
    database = make_url(database_url)
    if database.get_backend_name() == "sqlite":
        return create_engine(database_url, connect_args={"check_same_thread": False})
    if database.drivername == "postgresql+psycopg":
        return create_engine(database_url, pool_pre_ping=True)

    return create_engine(database_url)


engine = create_database_engine(settings.database_url)
SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    autoflush=False,
    expire_on_commit=False,
)


def initialize_database() -> None:
    if settings.is_production:
        run_production_database_preflight(engine)
        return

    import backend.app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_db_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
