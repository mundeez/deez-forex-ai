from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool
from app.config import get_settings

settings = get_settings()

# SQLite does not support connection-pooling kwargs
_is_sqlite = settings.DATABASE_URL.startswith("sqlite")
_engine_kwargs = {
    "echo": False,
    "future": True,
}
if not _is_sqlite:
    _engine_kwargs.update(
        pool_size=10,
        max_overflow=20,
        pool_recycle=3600,
        pool_pre_ping=True,
    )

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


# Celery workers create/destroy event loops per task; pooled asyncpg
# connections are tied to the loop that created them. Use NullPool
# so each task gets a fresh connection on its own loop.
def get_celery_session():
    """Return an async session factory safe for Celery (thread-per-task) use."""
    _engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        future=True,
        poolclass=NullPool,
    )
    return async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
