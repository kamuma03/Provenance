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
RUN optimum-cli export onnx --model "${RERANKER_MODEL}" \
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

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install workspace packages (editable) so any service entrypoint is importable.
COPY pyproject.toml ./
COPY packages ./packages
COPY services ./services
RUN uv pip install --system --break-system-packages \
        -e packages/contracts -e packages/service -e services

# Swap the CPU onnxruntime (pulled transitively by fastembed / rapidocr) for the CUDA build.
# The aarch64 + CUDA-13 wheel isn't on PyPI; it comes from NVIDIA's SBSA index. Same import
# name (`onnxruntime`), so once installed every ONNX model can use CUDAExecutionProvider.
RUN uv pip uninstall --system --break-system-packages onnxruntime \
    && uv pip install --system --break-system-packages \
        --extra-index-url https://pypi.jetson-ai-lab.io/sbsa/cu130 \
        "onnxruntime-gpu==1.24.0"

# Bake the exported reranker; provenance_services.reranker loads it from here on CUDA when
# RERANKER_MODEL=BAAI/bge-reranker-v2-m3 (the basename maps to <RERANKER_ONNX_ROOT>/<name>).
COPY --from=reranker-export /export/bge-reranker-v2-m3 /opt/models/bge-reranker-v2-m3

EXPOSE 8000
# Default command is overridden per service in docker-compose.yml.
CMD ["uvicorn", "provenance_services.gateway:app", "--host", "0.0.0.0", "--port", "8000"]
