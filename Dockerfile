FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install -e ".[dev]"

VOLUME ["/data"]
ENV EQM_DATA_DIR=/data \
    PORT=8080

EXPOSE 8080

CMD ["uvicorn", "eqm.api:app", "--host", "0.0.0.0", "--port", "8080"]
