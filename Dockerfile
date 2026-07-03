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

EXPOSE 8000
# Default command is overridden per service in docker-compose.yml.
CMD ["uvicorn", "provenance_services.gateway:app", "--host", "0.0.0.0", "--port", "8000"]
