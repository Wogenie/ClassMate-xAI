# ---------- Stage 1: build the React frontend ----------
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend

# Copy manifests first for layer caching
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Copy the rest and build
COPY frontend/ ./

# Optional: pass your Google Client ID at build time so the "Continue with
# Google" button works. e.g.  --build-arg VITE_GOOGLE_CLIENT_ID=xxx.apps.googleusercontent.com
ARG VITE_GOOGLE_CLIENT_ID=""
ENV VITE_GOOGLE_CLIENT_ID=$VITE_GOOGLE_CLIENT_ID

RUN npm run build

# ---------- Stage 2: Python backend + serve the built SPA ----------
FROM python:3.11-slim AS backend
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps for document ingestion (pypdf, pillow, tesseract bindings) and
# onnxruntime. Tesseract is optional at runtime but OCR screenshots need it.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        tesseract-ocr \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Copy backend source
COPY backend/requirements.txt /app/backend/requirements.txt
COPY backend/ /app/backend/

# Copy the built frontend (from stage 1) into the backend's expected location
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist

# Install python deps
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Healthcheck hits the FastAPI health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/health || exit 1

WORKDIR /app/backend

EXPOSE 8000

# Run uvicorn. Use one worker because the app holds in-memory bot/scheduler
# state that must not be duplicated; the container scales horizontally instead.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
