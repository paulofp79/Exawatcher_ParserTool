#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="ExaWatcher Streamlit"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

RUN_DIR="${EXAWATCHER_RUN_DIR:-${REPO_ROOT}/.run}"
PID_FILE="${EXAWATCHER_PID_FILE:-${RUN_DIR}/streamlit.pid}"
LOG_FILE="${EXAWATCHER_LOG_FILE:-${RUN_DIR}/streamlit.log}"
HOST="${EXAWATCHER_HOST:-0.0.0.0}"
PORT="${EXAWATCHER_PORT:-8099}"
MAX_UPLOAD_MB="${EXAWATCHER_MAX_UPLOAD_MB:-1048576}"
APP_FILE="${EXAWATCHER_APP_FILE:-${REPO_ROOT}/streamlit_app.py}"

usage() {
  cat <<USAGE
Usage: $0 {start|stop|restart|status|logs}

Environment overrides:
  EXAWATCHER_HOST       Bind address, default: 0.0.0.0
  EXAWATCHER_PORT       Port, default: 8099
  EXAWATCHER_MAX_UPLOAD_MB
                         Browser upload cap in MB, default: 1048576
  EXAWATCHER_RUN_DIR    Runtime dir, default: <repo>/.run
  EXAWATCHER_LOG_FILE   Log file, default: <repo>/.run/streamlit.log
  EXAWATCHER_PID_FILE   PID file, default: <repo>/.run/streamlit.pid
USAGE
}

streamlit_bin() {
  if [[ -x "${REPO_ROOT}/.venv/bin/streamlit" ]]; then
    printf '%s\n' "${REPO_ROOT}/.venv/bin/streamlit"
    return 0
  fi
  if command -v streamlit >/dev/null 2>&1; then
    command -v streamlit
    return 0
  fi
  printf 'ERROR: streamlit was not found. Create .venv and run: pip install -r requirements.txt\n' >&2
  return 1
}

pid_value() {
  if [[ -f "${PID_FILE}" ]]; then
    tr -d '[:space:]' < "${PID_FILE}"
  fi
}

is_running() {
  local pid
  pid="$(pid_value || true)"
  [[ -n "${pid}" ]] && kill -0 "${pid}" >/dev/null 2>&1
}

start_app() {
  if is_running; then
    printf '%s is already running. PID: %s\n' "${APP_NAME}" "$(pid_value)"
    status_app
    return 0
  fi

  if [[ ! -f "${APP_FILE}" ]]; then
    printf 'ERROR: app file not found: %s\n' "${APP_FILE}" >&2
    return 1
  fi

  mkdir -p "${RUN_DIR}"
  local bin
  bin="$(streamlit_bin)"

  printf 'Starting %s on %s:%s...\n' "${APP_NAME}" "${HOST}" "${PORT}"
  nohup "${bin}" run "${APP_FILE}" \
    --server.address "${HOST}" \
    --server.port "${PORT}" \
    --server.maxUploadSize "${MAX_UPLOAD_MB}" \
    > "${LOG_FILE}" 2>&1 &
  printf '%s\n' "$!" > "${PID_FILE}"

  sleep 2
  if is_running; then
    status_app
    return 0
  fi

  printf 'ERROR: %s did not stay running. Last log lines:\n' "${APP_NAME}" >&2
  tail -n 40 "${LOG_FILE}" >&2 || true
  return 1
}

stop_app() {
  if ! [[ -f "${PID_FILE}" ]]; then
    printf '%s is not running. No PID file found.\n' "${APP_NAME}"
    return 0
  fi

  local pid
  pid="$(pid_value || true)"
  if [[ -z "${pid}" ]] || ! kill -0 "${pid}" >/dev/null 2>&1; then
    printf 'Removing stale PID file: %s\n' "${PID_FILE}"
    rm -f "${PID_FILE}"
    return 0
  fi

  printf 'Stopping %s. PID: %s\n' "${APP_NAME}" "${pid}"
  kill "${pid}" >/dev/null 2>&1 || true
  for _ in {1..20}; do
    if ! kill -0 "${pid}" >/dev/null 2>&1; then
      rm -f "${PID_FILE}"
      printf '%s stopped.\n' "${APP_NAME}"
      return 0
    fi
    sleep 0.5
  done

  printf 'Process did not stop gracefully; sending SIGKILL.\n' >&2
  kill -9 "${pid}" >/dev/null 2>&1 || true
  rm -f "${PID_FILE}"
}

status_app() {
  if is_running; then
    local pid
    pid="$(pid_value)"
    printf '%s is running.\n' "${APP_NAME}"
    printf 'PID: %s\n' "${pid}"
    printf 'Bind: %s:%s\n' "${HOST}" "${PORT}"
    printf 'Upload cap: %s MB\n' "${MAX_UPLOAD_MB}"
    printf 'URL: http://127.0.0.1:%s\n' "${PORT}"
    printf 'Log: %s\n' "${LOG_FILE}"
    return 0
  fi

  if [[ -f "${PID_FILE}" ]]; then
    printf '%s is not running. Stale PID file: %s\n' "${APP_NAME}" "${PID_FILE}"
    return 1
  fi

  printf '%s is not running.\n' "${APP_NAME}"
}

logs_app() {
  if [[ ! -f "${LOG_FILE}" ]]; then
    printf 'No log file found: %s\n' "${LOG_FILE}"
    return 0
  fi
  tail -n "${LINES:-120}" "${LOG_FILE}"
}

case "${1:-status}" in
  start)
    start_app
    ;;
  stop)
    stop_app
    ;;
  restart)
    stop_app
    start_app
    ;;
  status)
    status_app
    ;;
  logs)
    logs_app
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
