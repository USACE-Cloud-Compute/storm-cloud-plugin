#!/bin/bash

CC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "CC_DIR: $CC_DIR"

echo "Starting MinIO instance and re-initializing buckets"
docker compose -f "$CC_DIR/minio/docker-compose.yml" down
docker compose -f "$CC_DIR/minio/docker-compose.yml" up -d

echo "Starting StormHub script with MinIO in Docker"
docker compose -f "$CC_DIR/docker-compose.yml" down
docker compose -f "$CC_DIR/docker-compose.yml" up -d