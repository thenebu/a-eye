# ── Stage 1: Build dlib/face_recognition ──────────────────────────
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake libopenblas-dev liblapack-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Stage 2: Runtime ────────��─────────────────────────��───────────
FROM python:3.12-slim

WORKDIR /app

# Copy pre-built Python packages from builder (no build tools needed)
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Runtime dependencies for dlib (BLAS) + gosu for privilege drop
RUN apt-get update && apt-get install -y --no-install-recommends \
    gosu libopenblas0 liblapack3 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r aeye && useradd -r -g aeye -d /app aeye \
    && mkdir -p /app/data/thumbnails \
    && chown -R aeye:aeye /app/data

COPY . .
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
