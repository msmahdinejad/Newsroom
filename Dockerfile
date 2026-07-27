FROM python:3.14-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client curl && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project --extra telegram

COPY src/ ./src/
COPY alembic.ini ./
RUN uv sync --frozen --no-dev --extra telegram --extra external-sources

# The optional capability layer is pinned to an immutable upstream revision.
ARG AGENT_REACH_PINNED_SHA=1494c2ab239e7355a77e7cceaf3271453a1f34b5
LABEL org.newsroom.agent-reach.revision=$AGENT_REACH_PINNED_SHA
RUN uv run python -c "import importlib.metadata as m; assert m.version('agent-reach') == '1.5.0'; assert m.version('twitter-cli') == '0.8.5'"

ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

# Run every application process as an unprivileged user.
RUN useradd -r -s /bin/false -m newsroom && \
    mkdir -p /home/newsroom/.cache/uv /tmp/uv-cache /data/sessions && \
    chown -R newsroom:newsroom /app /home/newsroom /tmp/uv-cache /data/sessions
ENV UV_CACHE_DIR=/tmp/uv-cache
USER newsroom

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=15s \
    CMD uv run python -m newsroom.service_status db

CMD ["uv", "run", "python", "-m", "newsroom.service_status", "db"]
