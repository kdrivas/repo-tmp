FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
COPY pipelines/ ./pipelines/

RUN --mount=type=secret,id=gar_token \
    UV_INDEX_MLOPS_LIB_USERNAME=oauth2accesstoken \
    UV_INDEX_MLOPS_LIB_PASSWORD=$(cat /run/secrets/gar_token) \
    uv sync --frozen --no-dev

RUN /app/.venv/bin/pyflyte-execute --help > /dev/null

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app"

CMD ["python"]
