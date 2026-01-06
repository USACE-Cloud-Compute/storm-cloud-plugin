#!/usr/bin/env bash
# run-cc-stormhub.sh
# ------------------------------------------
# Launch an interactive session from the
# Docker image `cc-stormhub-cloud` using the
# environment variables defined in
# `example.env`.

set -euo pipefail

IMAGE="cc-stormhub-cloud"
ENV_FILE="example.env"
CONTAINER_NAME="cc-stormhub-cloud-interactive"

# Ensure the env file exists before we continue.
if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Error: ${ENV_FILE} does not exist in $(pwd)." >&2
  exit 1
fi

# Default command is /bin/bash; allow user-supplied override.
CMD=("$@")
if [[ ${#CMD[@]} -eq 0 ]]; then
  CMD=(/bin/bash)
fi

# Run the container
docker run --rm -it \
  --name "${CONTAINER_NAME}" \
  --add-host host.docker.internal:host-gateway \
  --env-file "${ENV_FILE}" \
  "${IMAGE}" \
  "${CMD[@]}"