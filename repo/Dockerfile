FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc curl postgresql-client && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x /app/docker/api-entrypoint.sh /app/docker/worker-entrypoint.sh /app/docker/test-entrypoint.sh

ENV PYTHONPATH=/app

EXPOSE 8000
