# syntax=docker/dockerfile:1.6
# ============================================================
# TraqConverter backend — FastAPI + worker.
#   docker build -t traqconverter-backend .
#   docker run --env-file .env -p 8000:8000 traqconverter-backend
# Override CMD with `python -m worker.worker` to run the queue worker.
# ============================================================

FROM python:3.11-slim AS base

# System packages we need at runtime: tesseract for OCR, libs for PyMuPDF
# and PIL, plus build tools for any wheels that don't ship binaries.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    tesseract-ocr \
    libtesseract-dev \
    libgl1 \
    libglib2.0-0 \
    libjpeg62-turbo \
    libpng16-16 \
    fonts-dejavu-core \
    curl \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TESSERACT_CMD=/usr/bin/tesseract

WORKDIR /app

# Install Python deps first so unrelated source changes don't bust the layer.
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy the rest of the application
COPY . /app

# Don't run as root in production
RUN useradd --create-home --shell /bin/bash app \
 && chown -R app:app /app
USER app

EXPOSE 8000

# Healthcheck: hit the FastAPI root.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl --fail http://localhost:8000/ || exit 1

# Default to the API server. Override the CMD to run the worker.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
