FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

WORKDIR /app

RUN useradd -m -U appuser && chown -R appuser:appuser /app

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

COPY retriva-gateway/requirements.txt ./
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY retriva-gateway/pyproject.toml ./
COPY --chown=appuser:appuser retriva-gateway/src /app/src
RUN pip install --no-cache-dir .

USER appuser

EXPOSE 8002

CMD ["uvicorn", "retriva_gateway.main:app", "--host", "0.0.0.0", "--port", "8002"]

# ── Pro extensions stage ──────────────────────────────────────────────────
# Built when the Docker build targets "pro" (via docker-compose
# `target: pro` or `docker build --target pro`).
#
# The build context must include the Pro extension repos.  In the local
# containerized deployment, set RETRIVA_GATEWAY_CONTEXT=.. so the workspace
# parent is the build context.

FROM python:3.12-slim AS pro

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

WORKDIR /app

RUN useradd -m -U appuser && chown -R appuser:appuser /app

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

COPY retriva-gateway/requirements.txt ./
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY retriva-gateway/pyproject.toml ./
COPY --chown=appuser:appuser retriva-gateway/src /app/src
RUN pip install --no-cache-dir .

# Retriva Pro IAM Entra provider package (optional).
# When the retriva-iam-entra directory is present and contains a valid
# Python package (setup.py/pyproject.toml), it is pip-installed.  When
# absent or empty, the step is a no-op.
COPY retriva-iam-entra /tmp/retriva-iam-entra
RUN if [ -f /tmp/retriva-iam-entra/pyproject.toml ] || [ -f /tmp/retriva-iam-entra/setup.py ]; then \
      pip install --no-cache-dir /tmp/retriva-iam-entra; \
    fi && \
    rm -rf /tmp/retriva-iam-entra

USER appuser

EXPOSE 8002

CMD ["uvicorn", "retriva_gateway.main:app", "--host", "0.0.0.0", "--port", "8002"]
