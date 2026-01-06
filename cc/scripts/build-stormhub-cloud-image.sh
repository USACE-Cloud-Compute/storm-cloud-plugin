#!/bin/bash
# This script builds the StormHub Cloud Docker image

CC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "CC_DIR: $CC_DIR"

echo "Building StormHub Cloud Docker image"
docker compose -f "$CC_DIR/docker-compose.yml" build stormhub-cloud