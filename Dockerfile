FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client curl && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --extra dev --extra telegram

COPY src/ ./src/
COPY scripts/ ./scripts/
COPY tests/ ./tests/
COPY legacy/ ./legacy/
COPY alembic.ini ./
RUN uv sync --frozen --extra dev --extra telegram

ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

# Non-root user with writable cache dir
RUN useradd -r -s /bin/false -m newsroom && \
    mkdir -p /home/newsroom/.cache/uv /tmp/uv-cache /data/sessions && \
    chown -R newsroom:newsroom /app /home/newsroom /tmp/uv-cache /data/sessions
ENV UV_CACHE_DIR=/tmp/uv-cache
USER newsroom

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=15s \
    CMD uv run python -m newsroom.service_status db

CMD ["uv", "run", "python", "-m", "newsroom.service_status", "db"]
