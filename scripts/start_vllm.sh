#!/usr/bin/env bash
# Launch the local vLLM server that the ingestion/query LLM tasks route to.
#
# Why vLLM (not the compose Ollama tier): on the DGX Spark (GB10, aarch64 Blackwell),
# Ollama's llama.cpp backend does not batch — aggregate throughput is flat ~33 tok/s from 1
# to 16 concurrent requests, so the ingestion's concurrency is wasted. vLLM's continuous
# batching keeps the GPU fed (~300 tok/s at n=24), lifting end-to-end ingestion several-fold.
# It serves the SAME model (Qwen3.5-9B, the qwen3.5:9b tier) in FP8.
#
# vLLM runs as its own container (not in docker-compose.yml) because it needs the
# NVIDIA/vLLM image and the model in HF format, both outside the app image. The app reaches
# it by container name on the compose network; point the services at it with:
#   LLM_LOCAL_BASE_URL=http://vllm:8000/v1  (see ops/docker-compose.qdrant.yml usage)
#
# Resource notes (tunable via env):
#   GPU_MEM_UTIL=0.3   vLLM reserves this fraction of the unified 128GB for weights + KV
#                      cache. 0.3 (~36GB) fits the 10GB FP8 model with ample KV headroom;
#                      the default 0.9 would reserve ~110GB of KV cache it never uses and
#                      starve the host (OOM). Raise only if you see KV-cache-full warnings.
#   MAX_NUM_SEQS=16    concurrent sequences in a batch; bounds KV-cache pool size.
#   MAX_MODEL_LEN=8192 context window — extraction prompts are ~1-2k tokens, so this is ample
#                      and keeps the KV pool small (the model's native 262k would be wasteful).
#
# Usage: scripts/start_vllm.sh   (re-run to recreate with current settings; idempotent)
set -euo pipefail

IMAGE="${VLLM_IMAGE:-vllm/vllm-openai:latest-cu130}"     # CUDA 13 / Blackwell build
MODEL="${VLLM_MODEL:-Qwen/Qwen3.5-9B}"                   # HF repo; served as qwen3.5:9b
SERVED_NAME="${VLLM_SERVED_NAME:-qwen3.5:9b}"            # matches LLM_TIER_LOW in compose
NETWORK="${VLLM_NETWORK:-provenance_default}"            # the app's compose network
PORT="${VLLM_PORT:-8001}"                                # host port (container listens on 8000)
GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.3}"
MAX_NUM_SEQS="${MAX_NUM_SEQS:-16}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-8192}"
HF_CACHE="${HF_CACHE:-$HOME/.cache/huggingface}"        # persists downloaded weights

command -v docker >/dev/null || { echo "docker not found" >&2; exit 1; }
docker network inspect "$NETWORK" >/dev/null 2>&1 || {
  echo "network '$NETWORK' not found — bring the stack up first (docker compose ... up -d)" >&2
  exit 1
}

echo "recreating vLLM: model=$MODEL fp8 gpu_mem_util=$GPU_MEM_UTIL max_num_seqs=$MAX_NUM_SEQS"
docker rm -f vllm >/dev/null 2>&1 || true
mkdir -p "$HF_CACHE"
docker run -d --name vllm \
  --gpus all \
  --network "$NETWORK" \
  -p "127.0.0.1:${PORT}:8000" \
  --restart unless-stopped \
  --ipc=host \
  -v "$HF_CACHE:/root/.cache/huggingface" \
  "$IMAGE" \
  --model "$MODEL" \
  --served-model-name "$SERVED_NAME" \
  --quantization fp8 \
  --max-model-len "$MAX_MODEL_LEN" \
  --gpu-memory-utilization "$GPU_MEM_UTIL" \
  --max-num-seqs "$MAX_NUM_SEQS"

echo "waiting for vLLM to load (first run downloads ~19GB; reloads recompile CUDA graphs)…"
for _ in $(seq 1 120); do
  if curl -sf "http://localhost:${PORT}/v1/models" >/dev/null 2>&1; then
    echo "vLLM ready on http://localhost:${PORT}  (serving '${SERVED_NAME}')"
    exit 0
  fi
  sleep 5
done
echo "vLLM did not become ready in time — check: docker logs vllm" >&2
exit 1
