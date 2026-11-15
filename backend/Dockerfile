# MARS-X backend (FastAPI). Not built on the development machine (Docker daemon not running there).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MARSX_CACHE_DIR=/data/cache

WORKDIR /app

COPY requirements.txt requirements-geo.txt ./
RUN pip install -r requirements.txt -r requirements-geo.txt

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts
COPY tests ./tests

RUN mkdir -p /data/cache

EXPOSE 8000

# Apply migrations (creates PostGIS columns on PostgreSQL), then serve. Seeding runs in the app's lifespan hook.
CMD ["sh", "-c", "python -m alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
