# Single image for all P0 services; compose runs each as its own container with a
# per-service command. (Per-service images are a P1 hardening step.)
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install workspace packages (editable) so any service entrypoint is importable.
COPY pyproject.toml ./
COPY packages ./packages
COPY services ./services
RUN uv pip install --system -e packages/contracts -e packages/service -e services

EXPOSE 8000
# Default command is overridden per service in docker-compose.yml.
CMD ["uvicorn", "provenance_services.gateway:app", "--host", "0.0.0.0", "--port", "8000"]
