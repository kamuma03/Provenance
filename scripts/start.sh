#!/usr/bin/env bash
# Provenance — bring up the whole stack (8 services + NATS + Postgres + OTel,
# and the local LLM tier via Ollama when a GPU is present).
#
# Usage: scripts/start.sh [--llm|--no-llm] [--no-build] [--no-pull] [--logs] [--dry-run]
#   --llm / --no-llm   force the local LLM (Ollama) on/off (default: on iff an NVIDIA GPU)
#   --no-build         skip `docker compose build` (use existing images)
#   --no-pull          start Ollama but don't pull the tier models (do it later)
#   --logs             tail logs after everything is healthy
#   --dry-run          print what would run, change nothing
set -euo pipefail

cd "$(dirname "$0")/.."
COMPOSE=(docker compose -f ops/docker-compose.yml)

llm=auto; build=1; pull=1; logs=0; dry=0
for arg in "$@"; do
  case "$arg" in
    --llm) llm=on ;;
    --no-llm) llm=off ;;
    --no-build) build=0 ;;
    --no-pull) pull=0 ;;
    --logs) logs=1 ;;
    --dry-run) dry=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

run() { echo "+ $*"; [[ $dry -eq 1 ]] || "$@"; }

command -v docker >/dev/null || { echo "docker not found on PATH" >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "'docker compose' v2 required" >&2; exit 1; }

# ---- decide whether the local LLM tier comes up ----
has_gpu=0
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then has_gpu=1; fi
[[ $llm == auto ]] && { [[ $has_gpu -eq 1 ]] && llm=on || llm=off; }

if [[ $llm == on ]]; then
  # ollama-pull sits in its own profile so --no-pull genuinely skips it (review M-18).
  export COMPOSE_PROFILES=llm
  [[ $pull -eq 1 ]] && export COMPOSE_PROFILES=llm,llm-pull
  [[ $has_gpu -eq 1 ]] || echo "warning: --llm with no NVIDIA GPU detected — Ollama will run on CPU (slow)."
  echo "LLM tier: ON  (Ollama; synthesis/critique→high, planning/detection/extraction→low)"
else
  export LLM_LOCAL_BASE_URL=""   # no local server → services use the offline heuristic
  echo "LLM tier: OFF (heuristic agents; Claude tasks still run if ANTHROPIC_API_KEY is set)"
fi

[[ -f .env ]] || echo "note: no .env — Claude-routed tasks (eval_judge) need ANTHROPIC_API_KEY; see .env.example"

# ---- build + up ----
[[ $build -eq 1 ]] && run "${COMPOSE[@]}" build
run "${COMPOSE[@]}" up -d

if [[ $llm == on && $pull -eq 1 ]]; then
  echo "pulling tier models (qwen3.6:27b, qwen3.5:9b) in the background — watch with:"
  echo "    ${COMPOSE[*]} logs -f ollama-pull"
fi

# ---- wait for the gateway to report healthy ----
if [[ $dry -eq 0 ]]; then
  printf "waiting for gateway"
  for _ in $(seq 1 60); do
    if curl -sf http://localhost:8000/health >/dev/null 2>&1; then ok=1; break; fi
    printf "."; sleep 1
  done
  echo
  if [[ "${ok:-0}" -eq 1 ]]; then echo "gateway healthy ✓"; else
    echo "gateway did not become healthy in 60s — check: ${COMPOSE[*]} logs gateway" >&2; exit 1
  fi
fi

cat <<EOF

Provenance is up.
  Gateway / API   http://localhost:8000        (OpenAPI: /docs, health: /health)
$( [[ $llm == on ]] && echo "  Ollama (LLM)    http://localhost:11434       (OpenAI-compatible: /v1)" )
  Web UI          cd web && npm install && npm run dev   (http://localhost:3000)

  Logs   ${COMPOSE[*]} logs -f [service]
  Stop   scripts/stop.sh        (add --clean to drop data volumes)
EOF

# Explicit `if` (not a trailing `&&`): under `set -e` a false test as the last command would
# make a successful run exit non-zero, breaking any `start.sh && …` chain (review M-18).
if [[ $logs -eq 1 && $dry -eq 0 ]]; then
  exec "${COMPOSE[@]}" logs -f
fi
