FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client curl && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project

COPY src/ ./src/
COPY alembic.ini ./
RUN uv sync --frozen

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Non-root user with writable cache dir
RUN useradd -r -s /bin/false -m newsroom && \
    mkdir -p /home/newsroom/.cache/uv && \
    chown -R newsroom:newsroom /app /home/newsroom
ENV UV_CACHE_DIR=/tmp/uv-cache
USER newsroom

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=15s \
    CMD uv run python -c "from newsroom.storage.database import db_health; exit(0 if db_health() else 1)"

CMD ["uv", "run", "python", "-c", "from newsroom.storage.database import db_health; exit(0 if db_health() else 1)"]
