# ---- reranker ONNX export (build-only stage; discarded) ----
# BAAI/bge-reranker-v2-m3 (RERANKER_MODEL, R66) isn't carried by any fastembed release, so we
# export it to ONNX at build. CPU torch on a slim base is enough for a one-off export; only
# the ONNX + tokenizer are copied into the runtime image — no optimum/transformers/torch ship
# at runtime (the reranker loads it with onnxruntime + tokenizers). This stage is independent
# of the app code, so editing services/ doesn't re-trigger the (heavy) export.
FROM python:3.12-slim AS reranker-export
ENV DEBIAN_FRONTEND=noninteractive \
    HF_HUB_DISABLE_PROGRESS_BARS=1
RUN pip install --no-cache-dir --root-user-action=ignore \
        torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir --root-user-action=ignore \
        optimum-onnx transformers onnx onnxruntime numpy sentencepiece
ARG RERANKER_MODEL=BAAI/bge-reranker-v2-m3
# Cache the HuggingFace download across builds so a rebuild doesn't re-fetch the model — the
# review's air-gapped-rebuild concern (M-17). For a fully offline build, pre-populate this
# BuildKit cache once (or point HF_HOME at a mounted, pre-downloaded cache).
RUN --mount=type=cache,target=/root/.cache/huggingface \
    optimum-cli export onnx --model "${RERANKER_MODEL}" \
        --task text-classification /export/bge-reranker-v2-m3

# Single image for all services; compose runs each as its own container with a per-service
# command. GPU-enabled: the base carries the CUDA 13 + cuDNN runtime libraries so the ONNX
# models (fastembed embeddings + cross-encoder reranker, RapidOCR) can execute on the GPU
# via onnxruntime's CUDAExecutionProvider. CPU-only services share the same image harmlessly;
# GPU access is granted per-service in the compose GPU overlay (ops/docker-compose.gpu.yml),
# and each ONNX path only requests CUDA when PROVENANCE_ONNX_CUDA / PARSE_USE_GPU is set.
FROM nvidia/cuda:13.0.3-cudnn-runtime-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9.18 /uv /usr/local/bin/uv

WORKDIR /app

# Reproducible install (review H-13): all third-party deps come from ops/requirements.lock.txt
# (exported from uv.lock and drift-checked in CI), so the image can't diverge from the tested
# lockfile the way a fresh `uv pip install -e` resolution could. The workspace packages are then
# installed editable with --no-deps (no re-resolution) so their source is importable.
COPY pyproject.toml ./
COPY ops/requirements.lock.txt ./ops/requirements.lock.txt
COPY packages ./packages
COPY services ./services
RUN uv pip install --system --break-system-packages -r ops/requirements.lock.txt \
    && uv pip install --system --break-system-packages --no-deps \
        -e packages/contracts -e packages/service -e services

# Swap the CPU onnxruntime (pulled transitively by fastembed / rapidocr) for the CUDA build,
# but ONLY on arm64: the CUDA-13 wheel is aarch64-only (NVIDIA's SBSA index, not on PyPI), so
# attempting it on x86 would fail the build. On other arches (e.g. an x86 CI `docker build`)
# the CPU onnxruntime is kept and every ONNX model runs on CPU — the image still builds. The
# default auto-detects via TARGETARCH; force either way with --build-arg ONNXRUNTIME_GPU=1|0.
ARG TARGETARCH
ARG ONNXRUNTIME_GPU=auto
RUN set -eu; \
    want="$ONNXRUNTIME_GPU"; \
    if [ "$want" = auto ]; then { [ "$TARGETARCH" = arm64 ] && want=1 || want=0; }; fi; \
    if [ "$want" = 1 ]; then \
        echo "onnxruntime-gpu: installing CUDA build (arch=$TARGETARCH)"; \
        uv pip uninstall --system --break-system-packages onnxruntime; \
        uv pip install --system --break-system-packages \
            --extra-index-url https://pypi.jetson-ai-lab.io/sbsa/cu130 "onnxruntime-gpu==1.24.0"; \
    else \
        echo "onnxruntime-gpu: skipped, keeping CPU onnxruntime (arch=$TARGETARCH, arg=$ONNXRUNTIME_GPU)"; \
    fi

# Bake the exported reranker; provenance_services.reranker loads it from here on CUDA when
# RERANKER_MODEL=BAAI/bge-reranker-v2-m3 (the basename maps to <RERANKER_ONNX_ROOT>/<name>).
COPY --from=reranker-export /export/bge-reranker-v2-m3 /opt/models/bge-reranker-v2-m3

# Run as a non-root user (review H-13). /data is pre-created and owned by it so the graph
# service's Kuzu named volume (mounted at /data) inherits writable ownership on first use.
RUN useradd --system --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /data /opt/models
USER appuser

EXPOSE 8000

# Every service exposes /health on :8000 (create_app), and H-5 keeps it answerable under load,
# so one generic liveness probe fits them all (review H-13). Uses python3 (already present) to
# avoid adding curl to the image.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=4)" || exit 1

# Default command is overridden per service in docker-compose.yml.
CMD ["uvicorn", "provenance_services.gateway:app", "--host", "0.0.0.0", "--port", "8000"]
