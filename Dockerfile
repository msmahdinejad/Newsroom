FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    postgresql-client curl && \
    rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.cargo/bin:$PATH"

WORKDIR /app

COPY pyproject.toml README.md ./
RUN uv sync --frozen

COPY src/ ./src/
COPY migrations/ ./migrations/
COPY alembic.ini ./

ENV PYTHONPATH=/app
EXPOSE 8000

CMD ["uv", "run", "newsroom", "health"]
