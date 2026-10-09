import asyncio
import os
import subprocess
import sys
import uuid
from decimal import Decimal
from pathlib import Path

import asyncpg
import httpx
import pytest
import pytest_asyncio
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parent.parent

# Приложение читает DATABASE_URL при импорте, поэтому подменяем его на
# тестовую БД до первого импорта app.*.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    pytest.exit("TEST_DATABASE_URL is not set", returncode=2)
_url = make_url(TEST_DATABASE_URL)
if not _url.database or not _url.database.endswith("_test"):
    pytest.exit("TEST_DATABASE_URL must point to a *_test database", 2)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL


async def _create_database_if_missing() -> None:
    conn = await asyncpg.connect(
        host=_url.host,
        port=_url.port or 5432,
        user=_url.username,
        password=_url.password,
        database="postgres",
    )
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", _url.database
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{_url.database}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session", autouse=True)
def prepared_database():
    """Создаёт wallet_test (если нужно) и применяет миграции.

    Синхронная фикстура: alembic/env.py вызывает asyncio.run(), что
    нельзя делать внутри уже работающего event loop.
    """
    asyncio.run(_create_database_if_missing())
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        check=True,
    )


@pytest_asyncio.fixture
async def client():
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as http_client:
        yield http_client


@pytest.fixture
def create_wallet():
    """Фабрика кошельков с уникальным UUID (данные тестов не пересекаются)."""

    async def _create(balance: int = 0) -> uuid.UUID:
        from app.database import SessionFactory
        from app.models import Wallet

        wallet_id = uuid.uuid4()
        async with SessionFactory.begin() as session:
            session.add(Wallet(id=wallet_id, balance=Decimal(balance)))
        return wallet_id

    return _create
