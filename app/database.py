import os
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

DATABASE_URL = os.environ["DATABASE_URL"]

engine = create_async_engine(DATABASE_URL)

# expire_on_commit=False: после commit() атрибуты объекта остаются
# доступными; иначе их чтение в async-режиме вызвало бы lazy-load
# (MissingGreenlet).
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Отдельная сессия на каждый HTTP-запрос."""
    async with SessionFactory() as session:
        yield session
