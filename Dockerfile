FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

WORKDIR /app

RUN useradd -m -U appuser && chown -R appuser:appuser /app

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml ./
COPY --chown=appuser:appuser src /app/src
RUN pip install --no-cache-dir .

USER appuser

EXPOSE 8002

CMD ["uvicorn", "retriva_gateway.main:app", "--host", "0.0.0.0", "--port", "8002"]
