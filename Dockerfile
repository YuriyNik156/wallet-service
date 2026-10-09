FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /code

# Dev-зависимости (pytest, ruff) ставятся в тот же образ, чтобы тесты и
# проверку стиля можно было запускать в контейнере.
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY . .

EXPOSE 8000

# Миграции и seed выполняются до запуска Uvicorn; при ошибке любого шага
# (&&) контейнер завершается, и приложение не стартует.
CMD ["sh", "-c", "alembic upgrade head && python -m app.seed && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
