#!/usr/bin/env bash
# Build and push the story-tts image for linux/amd64 (required for RunPod).
# Usage: ./scripts/docker-build-push.sh [IMAGE_TAG]
# Default tag: fr4ilx/story-tts:latest

set -e
IMAGE="${1:-fr4ilx/story-tts:latest}"
cd "$(dirname "$0")/.."
echo "Building for linux/amd64: $IMAGE"
docker buildx build --platform linux/amd64 -t "$IMAGE" --push .
echo "Pushed $IMAGE"
