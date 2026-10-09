import asyncio
import uuid

import pytest
from sqlalchemy import select, update

from app.schemas import MAX_AMOUNT

BASE = "/api/v1/wallets"


def operation(client, wallet_id, operation_type, amount):
    return client.post(
        f"{BASE}/{wallet_id}/operation",
        json={"operation_type": operation_type, "amount": amount},
    )


async def get_balance(client, wallet_id) -> int:
    response = await client.get(f"{BASE}/{wallet_id}")
    assert response.status_code == 200
    return response.json()["balance"]


# --- GET ---------------------------------------------------------------


async def test_get_existing_wallet(client, create_wallet):
    wallet_id = await create_wallet(1000)

    response = await client.get(f"{BASE}/{wallet_id}")

    assert response.status_code == 200
    body = response.json()
    assert body == {"wallet_id": str(wallet_id), "balance": 1000}
    # Числовой тип в JSON, а не строка и не float.
    assert type(body["balance"]) is int


async def test_get_unknown_wallet_returns_404(client):
    response = await client.get(f"{BASE}/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Wallet not found"}


async def test_get_invalid_uuid_returns_422(client):
    response = await client.get(f"{BASE}/not-a-uuid")

    assert response.status_code == 422


# --- DEPOSIT / WITHDRAW ------------------------------------------------


async def test_deposit(client, create_wallet):
    wallet_id = await create_wallet(1000)

    response = await operation(client, wallet_id, "DEPOSIT", 500)

    assert response.status_code == 200
    body = response.json()
    assert body == {"wallet_id": str(wallet_id), "balance": 1500}
    assert type(body["balance"]) is int


async def test_deposit_is_visible_in_get(client, create_wallet):
    wallet_id = await create_wallet(1000)

    await operation(client, wallet_id, "DEPOSIT", 500)

    assert await get_balance(client, wallet_id) == 1500


async def test_withdraw(client, create_wallet):
    wallet_id = await create_wallet(1000)

    response = await operation(client, wallet_id, "WITHDRAW", 300)

    assert response.status_code == 200
    assert response.json() == {"wallet_id": str(wallet_id), "balance": 700}
    assert await get_balance(client, wallet_id) == 700


async def test_withdraw_entire_balance(client, create_wallet):
    wallet_id = await create_wallet(500)

    response = await operation(client, wallet_id, "WITHDRAW", 500)

    assert response.status_code == 200
    assert response.json()["balance"] == 0


async def test_withdraw_insufficient_funds(client, create_wallet):
    wallet_id = await create_wallet(500)

    response = await operation(client, wallet_id, "WITHDRAW", 600)

    assert response.status_code == 409
    assert response.json() == {"detail": "Insufficient funds"}
    assert await get_balance(client, wallet_id) == 500


async def test_deposit_max_amount(client, create_wallet):
    wallet_id = await create_wallet(0)

    response = await operation(client, wallet_id, "DEPOSIT", MAX_AMOUNT)

    assert response.status_code == 200
    assert response.json()["balance"] == MAX_AMOUNT


async def test_operation_on_unknown_wallet_returns_404(client):
    response = await operation(client, uuid.uuid4(), "DEPOSIT", 100)

    assert response.status_code == 404
    assert response.json() == {"detail": "Wallet not found"}


# --- Validation --------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"operation_type": "DEPOSIT", "amount": 0},
        {"operation_type": "DEPOSIT", "amount": -1},
        {"operation_type": "DEPOSIT", "amount": MAX_AMOUNT + 1},
        {"operation_type": "DEPOSIT", "amount": "1000"},
        {"operation_type": "DEPOSIT", "amount": 10.5},
        {"operation_type": "DEPOSIT", "amount": 1000.0},
        {"operation_type": "DEPOSIT", "amount": True},
        {"operation_type": "DEPOSIT", "amount": None},
        {"operation_type": "TRANSFER", "amount": 100},
        {"operation_type": "deposit", "amount": 100},
        {"amount": 100},
        {"operation_type": "DEPOSIT"},
        {},
    ],
)
async def test_invalid_operation_body_returns_422(
    client, create_wallet, payload
):
    wallet_id = await create_wallet(1000)

    response = await client.post(
        f"{BASE}/{wallet_id}/operation", json=payload
    )

    assert response.status_code == 422
    assert await get_balance(client, wallet_id) == 1000


async def test_operation_with_invalid_uuid_returns_422(client):
    response = await client.post(
        f"{BASE}/not-a-uuid/operation",
        json={"operation_type": "DEPOSIT", "amount": 100},
    )

    assert response.status_code == 422


# --- Concurrency -------------------------------------------------------


async def test_concurrent_withdrawals_on_one_wallet(client, create_wallet):
    wallet_id = await create_wallet(1000)

    responses = await asyncio.gather(
        *(operation(client, wallet_id, "WITHDRAW", 200) for _ in range(10))
    )

    statuses = sorted(r.status_code for r in responses)
    assert statuses == [200] * 5 + [409] * 5
    assert await get_balance(client, wallet_id) == 0


async def test_concurrent_deposits_and_withdrawals(client, create_wallet):
    initial = 300
    wallet_id = await create_wallet(initial)
    requests = [operation(client, wallet_id, "DEPOSIT", 100) for _ in range(5)]
    requests += [
        operation(client, wallet_id, "WITHDRAW", 200) for _ in range(5)
    ]

    responses = await asyncio.gather(*requests)

    statuses = [r.status_code for r in responses]
    assert set(statuses) <= {200, 409}
    deposits_ok = 5  # пополнения всегда успешны
    withdrawals_ok = statuses[5:].count(200)
    expected = initial + 100 * deposits_ok - 200 * withdrawals_ok
    final = await get_balance(client, wallet_id)
    assert final == expected
    assert final >= 0
    assert all(code == 200 for code in statuses[:5])


async def test_operation_waits_for_row_lock(client, create_wallet):
    """Запрос должен ждать блокировку строки и видеть актуальный баланс.

    Отдельная сессия держит FOR UPDATE и уменьшает баланс до 300. Если бы
    API читал баланс без блокировки, он увидел бы 1000 и списал 600.
    """
    from app.database import SessionFactory
    from app.models import Wallet

    wallet_id = await create_wallet(1000)

    async with SessionFactory() as locker:
        async with locker.begin():
            await locker.execute(
                select(Wallet).where(Wallet.id == wallet_id).with_for_update()
            )
            pending = asyncio.create_task(
                operation(client, wallet_id, "WITHDRAW", 600)
            )

            done, _ = await asyncio.wait({pending}, timeout=0.5)
            assert not done, "операция не дождалась блокировки строки"

            await locker.execute(
                update(Wallet)
                .where(Wallet.id == wallet_id)
                .values(balance=Wallet.balance - 700)
            )
        # locker.begin() завершён: транзакция зафиксирована, блокировка снята

    response = await asyncio.wait_for(pending, timeout=5)

    assert response.status_code == 409
    assert response.json() == {"detail": "Insufficient funds"}
    assert await get_balance(client, wallet_id) == 300
