FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/data/meme_collector.sqlite3

WORKDIR /app

RUN useradd --create-home --shell /bin/bash appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /data /app

COPY pyproject.toml README.md ./
COPY meme_collector_app ./meme_collector_app

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

USER appuser
EXPOSE 8000

CMD ["uvicorn", "meme_collector_app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
