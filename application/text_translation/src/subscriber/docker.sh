#!/usr/bin/env bash
set -euo pipefail

image_tag="${1:-continuum-text-translation-subscriber:local}"

docker buildx build \
    --platform linux/amd64 \
    --load \
    --tag "${image_tag}" \
    .
