from contextlib import contextmanager
import logging
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import get_settings

logger = logging.getLogger("qhealth.database")

class Base(DeclarativeBase):
    pass

settings = get_settings()
settings.initialize_directories()

if settings.is_postgres_enabled:
    # Target custom schema in PostgreSQL
    Base.metadata.schema = settings.effective_schema
    engine = create_engine(
        settings.normalized_database_url,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=5,
        max_overflow=10,
    )
    logger.info("postgres_engine_configured schema=%s", settings.effective_schema)
else:
    engine = create_engine(
        f"sqlite:///{settings.root / 'data' / 'qhealth.sqlite3'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

@contextmanager
def session_scope():
    with SessionLocal() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise

def init_db():
    if settings.is_postgres_enabled:
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{settings.effective_schema}";'))
        logger.info("schema_verified schema=%s", settings.effective_schema)
    
    from .storage import entities  # Register all tables.
    Base.metadata.create_all(engine)
    logger.info("tables_verified database=%s", "postgresql" if settings.is_postgres_enabled else "sqlite")

    if settings.is_supabase_storage_enabled:
        from .storage.supabase_storage import ensure_bucket_exists
        ensure_bucket_exists()

