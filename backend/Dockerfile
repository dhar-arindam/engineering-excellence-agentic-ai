FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install uv

COPY pyproject.toml .
RUN uv pip install --system --no-cache -e ".[dev]"

COPY . .

RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
# Pre-create the scans tmp dir with open permissions so volume mounts don't
# need a separate init step in local/non-volume setups.
RUN mkdir -p /tmp/scans && chmod 1777 /tmp/scans
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
