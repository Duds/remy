# ── Stage 1: Builder ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

# Build-time HuggingFace token for authenticated downloads (higher rate limits)
ARG HF_TOKEN

WORKDIR /build

# Install build tools needed by some Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies into an isolated prefix
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt
# sqlite-vec 0.1.6 ships a 32-bit arm binary in its linux/aarch64 wheel (upstream bug).
# Override with the alpha that ships the correct 64-bit aarch64 build.
RUN pip install --no-cache-dir --prefix=/install --pre "sqlite-vec>=0.1.7a10"

# Pre-download the sentence-transformers model at build time
# This avoids a slow cold-start when the first message arrives
# HF_HOME points to where the cache will be copied in the runtime stage
# HF_TOKEN enables authenticated downloads with higher rate limits
# ORT_DISABLE_ALL_GRAPH_OPTIMIZATION prevents ONNX runtime thread-safety issues
# OMP_NUM_THREADS=1 forces single-threaded execution to avoid race conditions
RUN --mount=type=secret,id=HF_TOKEN,env=HF_TOKEN \
    PYTHONPATH=/install/lib/python3.12/site-packages \
    HF_HOME=/root/.cache/huggingface \
    ORT_DISABLE_ALL_GRAPH_OPTIMIZATION=1 \
    OMP_NUM_THREADS=1 \
    python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')" \
    && find /root/.cache/huggingface -name "*.lock" -delete

# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# ffmpeg required by faster-whisper; curl for healthcheck; git for git_log/git_diff/git_status (US-git-commits-and-diffs)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg curl git \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user for security
RUN groupadd --gid 1001 remy && \
    useradd --uid 1001 --gid remy --shell /bin/bash --create-home remy

WORKDIR /app

# Copy installed packages and pre-downloaded model cache from builder
# Cache goes to /home/remy/.cache so the remy user can actually traverse to it
# (/root is drwx------ — chown-ing its contents doesn't help if /root itself blocks traversal)
COPY --from=builder /install /usr/local
COPY --chown=remy:remy --from=builder /root/.cache/huggingface /home/remy/.cache/huggingface

# Copy application source and config (owned by remy user)
COPY --chown=remy:remy remy/ remy/
COPY --chown=remy:remy config/ config/

# /data is mounted from Azure Files — persistent across container restarts
# Pre-create it so the volume mount doesn't need root
RUN mkdir -p /data && chown remy:remy /data
VOLUME /data

# Health check endpoint port (lightweight HTTP server in main.py)
EXPOSE 8080

# Runtime environment defaults
# ORT_DISABLE_ALL_GRAPH_OPTIMIZATION prevents ONNX runtime "Artifact already registered" errors
# OMP_NUM_THREADS=1 forces single-threaded ONNX execution to avoid race conditions
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AZURE_ENVIRONMENT=true \
    DATA_DIR=/data \
    HEALTH_PORT=8080 \
    HF_HOME=/home/remy/.cache/huggingface \
    ORT_DISABLE_ALL_GRAPH_OPTIMIZATION=1 \
    OMP_NUM_THREADS=1

# Docker HEALTHCHECK — Azure uses its own probes but this works for local docker
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${HEALTH_PORT}/health || exit 1

USER remy

CMD ["python3", "-m", "remy.main"]
