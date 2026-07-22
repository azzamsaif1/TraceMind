FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# tesseract enables real OCR text evidence (optional; the app degrades honestly
# without it). libpq for PostgreSQL.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN pip install -e . --no-deps

EXPOSE 8000

# Apply migrations, then serve.
CMD ["sh", "-c", "alembic upgrade head && uvicorn rusted_recall.web.app:app --host 0.0.0.0 --port 8000"]
