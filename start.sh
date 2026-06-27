#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${ROOT_DIR}/.run-logs"
PID_FILE="${LOG_DIR}/aggregator.pid"
ENV_FILE="${LOG_DIR}/aggregator.env"
LOG_FILE="${LOG_DIR}/aggregator.log"
AGGREGATOR_HOST="${AGGREGATOR_HOST:-127.0.0.1}"
AGGREGATOR_PORT_START="${AGGREGATOR_PORT:-8890}"

mkdir -p "${LOG_DIR}"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

port_in_use() {
  local port="$1"
  lsof -tiTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1
}

find_free_port() {
  local port="$1"
  while port_in_use "${port}"; do
    port=$((port + 1))
  done
  echo "${port}"
}

write_env_file() {
  local port="$1"
  local pid="$2"
  cat > "${ENV_FILE}" <<EOF
AGGREGATOR_HOST=${AGGREGATOR_HOST}
AGGREGATOR_PORT=${port}
AGGREGATOR_URL=http://${AGGREGATOR_HOST}:${port}
AGGREGATOR_HEALTH_URL=http://${AGGREGATOR_HOST}:${port}/api/aggregate/health
AGGREGATOR_LOG=${LOG_FILE}
AGGREGATOR_PID=${pid}
EOF
}

wait_for_service() {
  local url="$1"
  local pid="$2"

  for _ in $(seq 1 25); do
    if curl -fsS --max-time 2 "${url}" >/dev/null 2>&1; then
      return 0
    fi
    if ! kill -0 "${pid}" 2>/dev/null; then
      echo "Aggregator exited before becoming ready." >&2
      tail -n 40 "${LOG_FILE}" >&2 || true
      return 1
    fi
    sleep 1
  done

  echo "Aggregator did not become ready: ${url}" >&2
  tail -n 40 "${LOG_FILE}" >&2 || true
  return 1
}

cleanup_stale_state() {
  if [[ -f "${PID_FILE}" ]]; then
    existing_pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
    if [[ -z "${existing_pid}" ]] || ! kill -0 "${existing_pid}" 2>/dev/null; then
      rm -f "${PID_FILE}" "${ENV_FILE}"
    fi
  fi
}

require_command python3
require_command lsof
require_command curl
cleanup_stale_state

if [[ -f "${PID_FILE}" ]]; then
  existing_pid="$(cat "${PID_FILE}")"
  if [[ -n "${existing_pid}" ]] && kill -0 "${existing_pid}" 2>/dev/null; then
    if [[ -f "${ENV_FILE}" ]]; then
      # shellcheck disable=SC1090
      source "${ENV_FILE}"
      if [[ -n "${AGGREGATOR_HEALTH_URL:-}" ]] && curl -fsS --max-time 2 "${AGGREGATOR_HEALTH_URL}" >/dev/null 2>&1; then
        echo "Aggregator already running: ${AGGREGATOR_URL} (PID ${existing_pid})"
        exit 0
      fi
    fi
  fi
fi

AGGREGATOR_PORT="$(find_free_port "${AGGREGATOR_PORT_START}")"
AGGREGATOR_URL="http://${AGGREGATOR_HOST}:${AGGREGATOR_PORT}"
AGGREGATOR_HEALTH_URL="${AGGREGATOR_URL}/api/aggregate/health"

: > "${LOG_FILE}"
AGGREGATOR_PID="$(python3 "${ROOT_DIR}/scripts/launch_aggregator.py" "${ROOT_DIR}" "${LOG_FILE}" "${AGGREGATOR_HOST}" "${AGGREGATOR_PORT}")"

echo "${AGGREGATOR_PID}" > "${PID_FILE}"
write_env_file "${AGGREGATOR_PORT}" "${AGGREGATOR_PID}"
wait_for_service "${AGGREGATOR_HEALTH_URL}" "${AGGREGATOR_PID}"

echo "Aggregator started"
echo "  URL    : ${AGGREGATOR_URL}"
echo "  Health : ${AGGREGATOR_HEALTH_URL}"
echo "  Config : ${AGGREGATOR_URL}/api/aggregate/config"
echo "  PID    : ${AGGREGATOR_PID}"
echo "  Log    : ${LOG_FILE}"
