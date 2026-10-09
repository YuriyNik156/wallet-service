import enum
import uuid

from pydantic import BaseModel, Field, StrictInt

# Верхняя граница суммы одной операции. Намного меньше предела колонки
# NUMERIC(20, 0), поэтому переполнение хранилища недостижимо.
MAX_AMOUNT = 10**12


class OperationType(str, enum.Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAW = "WITHDRAW"


class OperationRequest(BaseModel):
    operation_type: OperationType
    # StrictInt: строки, дробные числа и bool отклоняются (HTTP 422).
    amount: StrictInt = Field(gt=0, le=MAX_AMOUNT)


class WalletResponse(BaseModel):
    wallet_id: uuid.UUID
    # int, а не Decimal: Pydantic сериализует Decimal в JSON строкой.
    balance: int
