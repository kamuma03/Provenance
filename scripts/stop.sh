#!/usr/bin/env bash
# Provenance — stop the stack. `--clean` also drops data volumes (Kuzu, Ollama models).
set -euo pipefail
cd "$(dirname "$0")/.."
COMPOSE=(docker compose -f ops/docker-compose.yml --profile llm)

if [[ "${1:-}" == "--clean" ]]; then
  echo "stopping and removing volumes (Kuzu graph + Ollama models will be lost)…"
  exec "${COMPOSE[@]}" down --volumes
fi
echo "stopping (data volumes preserved)…"
exec "${COMPOSE[@]}" down
