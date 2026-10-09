# Wallet Service

REST API для работы с балансами кошельков (тестовое задание).

**Стек:** Python 3.12, FastAPI, Uvicorn, SQLAlchemy (async) + asyncpg,
PostgreSQL 16, Alembic, Pydantic, pytest + pytest-asyncio + HTTPX, Ruff,
Docker Compose.

## Запуск

```bash
docker compose up --build
```

`.env` не нужен: в `docker-compose.yml` есть значения по умолчанию для
локальной разработки (`.env.example` перечисляет переменные, которые можно
переопределить). Порт PostgreSQL на хост не публикуется.

При старте контейнер `app` последовательно выполняет:

1. `alembic upgrade head` — миграции;
2. `python -m app.seed` — создаёт демонстрационный кошелёк;
3. `uvicorn` — запуск API на `http://localhost:8000`.

Если шаг 1 или 2 завершился ошибкой, контейнер останавливается, и API не
стартует. PostgreSQL имеет healthcheck (по TCP), `app` ждёт `service_healthy`.

> Миграции запускаются из команды контейнера, поэтому схема рассчитана на
> **одну реплику** приложения. Для нескольких реплик понадобился бы отдельный
> шаг миграций.

Swagger UI: `http://localhost:8000/docs`.

## API

| Метод | URL | Описание |
| --- | --- | --- |
| GET | `/api/v1/wallets/{wallet_uuid}` | Текущий баланс |
| POST | `/api/v1/wallets/{wallet_uuid}/operation` | `DEPOSIT` / `WITHDRAW` |

Тело `POST`: `{"operation_type": "DEPOSIT" | "WITHDRAW", "amount": 1000}`.

Успешный ответ обоих методов (HTTP 200):
`{"wallet_id": "<uuid>", "balance": 1500}` — `balance` всегда число.

| Ситуация | Код | Тело |
| --- | --- | --- |
| Кошелёк не найден | 404 | `{"detail": "Wallet not found"}` |
| Недостаточно средств | 409 | `{"detail": "Insufficient funds"}` |
| Невалидный UUID / тело запроса | 422 | стандартный формат FastAPI |

### Демонстрационный кошелёк

UUID: `00000000-0000-4000-8000-000000000001` (начальный баланс 1000;
повторный запуск seed баланс не сбрасывает).

```bash
W=00000000-0000-4000-8000-000000000001

curl http://localhost:8000/api/v1/wallets/$W

curl -X POST http://localhost:8000/api/v1/wallets/$W/operation \
  -H "Content-Type: application/json" \
  -d '{"operation_type": "DEPOSIT", "amount": 500}'

curl -X POST http://localhost:8000/api/v1/wallets/$W/operation \
  -H "Content-Type: application/json" \
  -d '{"operation_type": "WITHDRAW", "amount": 200}'
```

## Принятые допущения

- API работает с **целыми рублями**: `amount` — строго целое число
  `1 ≤ amount ≤ 10^12`; строки, дробные числа и `bool` отклоняются (422).
  Копейки и валюты не поддерживаются.
- Кошельки **не создаются автоматически**: операция над неизвестным UUID
  возвращает 404. Публичного endpoint'а создания нет (его нет в ТЗ);
  демонстрационный кошелёк создаёт seed.
- Баланс хранится как `NUMERIC(20, 0)` с `CHECK (balance >= 0)`.
- Валидация тела запроса выполняется до обращения к БД, поэтому некорректный
  запрос к несуществующему кошельку вернёт 422, а не 404.

## Конкурентность

Изменение баланса выполняется в одной транзакции
(`async with session.begin()`):

```
BEGIN → SELECT ... FOR UPDATE → проверка → изменение баланса → COMMIT
```

`SELECT ... FOR UPDATE` блокирует строку кошелька до конца транзакции.
Параллельный запрос к тому же кошельку ждёт, затем (на стандартном уровне
изоляции `READ COMMITTED`) читает уже актуальную строку и проверяет баланс
заново, поэтому потерянных обновлений и ухода в минус не бывает. При
недостатке средств исключение откатывает транзакцию. Разные кошельки
блокируются независимо. Блокировка действует на уровне PostgreSQL, а не
процесса, поэтому корректно работает и при нескольких воркерах Uvicorn.
`CHECK (balance >= 0)` — дополнительная защита на уровне БД.

Для каждого HTTP-запроса создаётся отдельная `AsyncSession`.

## Тесты и Ruff

```bash
docker compose run --rm app pytest
docker compose run --rm app ruff check .
```

Тесты работают с настоящим PostgreSQL в отдельной базе `wallet_test`
(создаётся автоматически, миграции применяются из Alembic;
рабочая БД `wallet` не затрагивается). Набор включает:

- GET/POST, 404, 409, валидацию и числовой тип `balance` в JSON;
- 10 параллельных списаний по 200 при балансе 1000 (ровно 5 × 200 и 5 × 409,
  итог 0) и параллельные пополнения и списания;
- детерминированный тест блокировки: отдельная сессия держит
  `FOR UPDATE` и меняет баланс, а API-запрос обязан ждать и увидеть новый
  баланс.

Проверка самих тестов: при временном удалении `.with_for_update()` из
`app/wallets.py` падают оба конкурентных теста и тест блокировки.

Локально без Docker: установить `requirements-dev.txt`, задать
`TEST_DATABASE_URL` (например
`postgresql+asyncpg://user:pass@localhost:5432/wallet_test`; имя БД должно
оканчиваться на `_test`) и выполнить `pytest`.

## Структура

```
app/
  main.py       — приложение FastAPI
  database.py   — engine, session factory, зависимость get_session
  models.py     — модель Wallet
  schemas.py    — Pydantic-схемы, MAX_AMOUNT
  wallets.py    — маршруты и функция apply_operation
  seed.py       — идемпотентный seed демонстрационного кошелька
alembic/        — асинхронные миграции
tests/          — API-тесты на PostgreSQL
```
