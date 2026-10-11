from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import Settings


class Base(DeclarativeBase):
    pass


class Database:
    """Owns the engine and session factory for one application instance."""

    def __init__(self, settings: Settings) -> None:
        self.engine: Engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
        )
        self.session_factory: sessionmaker[Session] = sessionmaker(
            bind=self.engine, expire_on_commit=False
        )

    def session(self) -> Session:
        return self.session_factory()

    def dispose(self) -> None:
        self.engine.dispose()
