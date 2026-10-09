import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Wallet
from app.schemas import (
    OperationRequest,
    OperationType,
    WalletResponse,
)

router = APIRouter(prefix="/api/v1/wallets", tags=["wallets"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

_NOT_FOUND = {"description": "Wallet not found"}
_INSUFFICIENT_FUNDS = {"description": "Insufficient funds"}


def _wallet_not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Wallet not found")


def _to_response(wallet: Wallet) -> WalletResponse:
    # Decimal с нулевой дробной частью (NUMERIC(20, 0)) -> int без потерь.
    return WalletResponse(wallet_id=wallet.id, balance=int(wallet.balance))


async def apply_operation(
    session: AsyncSession,
    wallet_id: uuid.UUID,
    operation_type: OperationType,
    amount: int,
) -> Wallet:
    """Выполняет операцию над кошельком в одной транзакции.

    Строка кошелька блокируется (SELECT ... FOR UPDATE) до чтения баланса
    и удерживается до commit/rollback, поэтому конкурентные операции над
    одним кошельком выполняются строго последовательно и видят актуальный
    баланс. Исключение внутри блока откатывает транзакцию.
    """
    async with session.begin():
        wallet = await session.scalar(
            select(Wallet)
            .where(Wallet.id == wallet_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if wallet is None:
            raise _wallet_not_found()

        if operation_type is OperationType.DEPOSIT:
            wallet.balance += Decimal(amount)
        else:
            if wallet.balance < amount:
                raise HTTPException(
                    status.HTTP_409_CONFLICT, "Insufficient funds"
                )
            wallet.balance -= Decimal(amount)
        wallet.updated_at = func.now()
    return wallet


@router.get(
    "/{wallet_uuid}",
    response_model=WalletResponse,
    responses={404: _NOT_FOUND},
)
async def get_wallet(
    wallet_uuid: uuid.UUID,
    session: SessionDep,
) -> WalletResponse:
    wallet = await session.get(Wallet, wallet_uuid)
    if wallet is None:
        raise _wallet_not_found()
    return _to_response(wallet)


@router.post(
    "/{wallet_uuid}/operation",
    response_model=WalletResponse,
    responses={404: _NOT_FOUND, 409: _INSUFFICIENT_FUNDS},
)
async def wallet_operation(
    wallet_uuid: uuid.UUID,
    body: OperationRequest,
    session: SessionDep,
) -> WalletResponse:
    wallet = await apply_operation(
        session, wallet_uuid, body.operation_type, body.amount
    )
    return _to_response(wallet)
