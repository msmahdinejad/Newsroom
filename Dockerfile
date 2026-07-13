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
COPY alembic.ini ./

ENV PYTHONPATH=/app
ENV DATABASE_URL=postgresql+psycopg://newsroom:newsroom_dev@postgres:5432/newsroom

CMD ["uv", "run", "newsroom", "health"]
