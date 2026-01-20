#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_DIR="${ROOT_DIR}/ha-config"
CUSTOM_COMPONENTS_DIR="${ROOT_DIR}/custom_components"

mkdir -p "${CONFIG_DIR}"

if [ ! -f "${CONFIG_DIR}/configuration.yaml" ]; then
  cat > "${CONFIG_DIR}/configuration.yaml" <<'YAML'
default_config:
logger:
  default: info
  logs:
    custom_components.elektro_15min_average: debug
YAML
fi

podman run --rm -it \
  -p 8123:8123 \
  -v "${CONFIG_DIR}:/config" \
  -v "${CUSTOM_COMPONENTS_DIR}:/config/custom_components" \
  -e TZ="${TZ:-UTC}" \
  ghcr.io/home-assistant/home-assistant:stable
