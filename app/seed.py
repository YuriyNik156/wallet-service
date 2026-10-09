"""Идемпотентное создание демонстрационного кошелька.

Запуск: python -m app.seed
Повторный запуск не создаёт дубликатов и не меняет существующий баланс.
"""

import asyncio
import uuid

from sqlalchemy.dialects.postgresql import insert

from app.database import SessionFactory, engine
from app.models import Wallet

DEMO_WALLET_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
DEMO_BALANCE = 1000


async def seed() -> None:
    async with SessionFactory.begin() as session:
        await session.execute(
            insert(Wallet)
            .values(id=DEMO_WALLET_ID, balance=DEMO_BALANCE)
            .on_conflict_do_nothing(index_elements=[Wallet.id])
        )
    await engine.dispose()
    print(f"Demo wallet: {DEMO_WALLET_ID}")


if __name__ == "__main__":
    asyncio.run(seed())
