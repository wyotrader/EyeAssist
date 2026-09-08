#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -eq 0 ]; then
  echo "Refusing to run EyeAssist rehearsal as root." >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
EXPECTED_ROOT="/home/jwhitman/eyeassist-clean"

if [ "${REPO_ROOT}" != "${EXPECTED_ROOT}" ]; then
  echo "Refusing to run outside authoritative repo: ${EXPECTED_ROOT}" >&2
  exit 1
fi

cd "${REPO_ROOT}"

HOST="127.0.0.1"
PORT="8088"
ORCHESTRATOR_HOST="127.0.0.1"
ORCHESTRATOR_PORT="${REHEARSAL_ORCHESTRATOR_PORT:-18300}"
UI_DIR="${REPO_ROOT}/eyeassist-ui"
PIPELINE_DIR="${REPO_ROOT}/pipeline"
ORCHESTRATOR_DIR="${PIPELINE_DIR}/orchestrator"
VENV_PY="${REPO_ROOT}/.venv/bin/python"
VENV_UVICORN="${REPO_ROOT}/.venv/bin/uvicorn"
STATIC_DIR="${UI_DIR}/build"
RUNTIME_DIR="$(mktemp -d /tmp/eyeassist-rehearsal.XXXXXX)"
DB_PATH="${RUNTIME_DIR}/rehearsal-auth.db"
LOG_PATH="${RUNTIME_DIR}/gateway.log"
ORCHESTRATOR_LOG_PATH="${RUNTIME_DIR}/orchestrator.log"
export DB_PATH

cleanup() {
  if [ -n "${ORCHESTRATOR_PID:-}" ] && kill -0 "${ORCHESTRATOR_PID}" 2>/dev/null; then
    kill "${ORCHESTRATOR_PID}" 2>/dev/null || true
    wait "${ORCHESTRATOR_PID}" 2>/dev/null || true
  fi
  if [ -n "${GATEWAY_PID:-}" ] && kill -0 "${GATEWAY_PID}" 2>/dev/null; then
    kill "${GATEWAY_PID}" 2>/dev/null || true
    wait "${GATEWAY_PID}" 2>/dev/null || true
  fi
  rm -rf "${RUNTIME_DIR}"
}
trap cleanup EXIT INT TERM

if [ ! -x "${VENV_PY}" ] || [ ! -x "${VENV_UVICORN}" ]; then
  echo "Candidate .venv is missing python or uvicorn." >&2
  exit 1
fi

if [ ! -f "${STATIC_DIR}/index.html" ]; then
  echo "Frontend build not found at ${STATIC_DIR}; run npm run build in eyeassist-ui first." >&2
  exit 1
fi

if ss -ltn "sport = :${PORT}" | grep -q ":${PORT}"; then
  echo "Refusing to start: ${HOST}:${PORT} is already in use." >&2
  exit 1
fi

if ss -ltn "sport = :${ORCHESTRATOR_PORT}" | grep -q ":${ORCHESTRATOR_PORT}"; then
  echo "Refusing to start: ${ORCHESTRATOR_HOST}:${ORCHESTRATOR_PORT} is already in use." >&2
  exit 1
fi

export REHEARSAL_ADMIN_EMAIL="${REHEARSAL_ADMIN_EMAIL:-admin.rehearsal@example.test}"
export REHEARSAL_ADMIN_PASSWORD="${REHEARSAL_ADMIN_PASSWORD:-rehearsal-admin-password}"
export REHEARSAL_CLINICIAN_EMAIL="${REHEARSAL_CLINICIAN_EMAIL:-clinician.rehearsal@example.test}"
export REHEARSAL_CLINICIAN_PASSWORD="${REHEARSAL_CLINICIAN_PASSWORD:-rehearsal-clinician-password}"

"${VENV_PY}" - <<'PY' 2>>"${LOG_PATH}"
import os
import sqlite3
from passlib.context import CryptContext

db_path = os.environ["DB_PATH"]
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
users = [
    ("admin-rehearsal", "Rehearsal Admin", os.environ["REHEARSAL_ADMIN_EMAIL"], "admin", os.environ["REHEARSAL_ADMIN_PASSWORD"]),
    ("clinician-rehearsal", "Rehearsal Clinician", os.environ["REHEARSAL_CLINICIAN_EMAIL"], "user", os.environ["REHEARSAL_CLINICIAN_PASSWORD"]),
]

conn = sqlite3.connect(db_path)
conn.execute("create table auth (id text primary key, email text, password text, active boolean)")
conn.execute("create table user (id text primary key, name text, email text, role text, profile_image_url text)")
for user_id, name, email, role, password in users:
    conn.execute("insert into auth values (?,?,?,?)", (user_id, email, pwd.hash(password), True))
    conn.execute("insert into user values (?,?,?,?,?)", (user_id, name, email, role, ""))
conn.commit()
conn.close()
PY

export DATABASE_URL="sqlite:///${DB_PATH}"
export EYEASSIST_SESSION_SECRET="${EYEASSIST_SESSION_SECRET:-$("${VENV_PY}" - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)}"
export EYEASSIST_SESSION_COOKIE="${EYEASSIST_SESSION_COOKIE:-eyeassist_rehearsal_session}"
export EYEASSIST_SESSION_SECURE="false"
export EYEASSIST_STATIC_DIR="${STATIC_DIR}"
export ORCHESTRATOR_URL="${ORCHESTRATOR_URL:-http://${ORCHESTRATOR_HOST}:${ORCHESTRATOR_PORT}}"
export RAG_SERVICE_URL="${RAG_SERVICE_URL:-http://127.0.0.1:8100}"
export VISION_SERVICE_URL="${VISION_SERVICE_URL:-http://127.0.0.1:8200}"
export OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"
export OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5:3b}"
export OLLAMA_SYNTHESIS_NUM_PREDICT="${OLLAMA_SYNTHESIS_NUM_PREDICT:-1024}"
export OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:-10m}"

PYTHONPATH="${PIPELINE_DIR}:${PYTHONPATH:-}" "${VENV_UVICORN}" orchestrator:app \
  --app-dir "${ORCHESTRATOR_DIR}" \
  --host "${ORCHESTRATOR_HOST}" \
  --port "${ORCHESTRATOR_PORT}" \
  --no-access-log \
  >"${ORCHESTRATOR_LOG_PATH}" 2>&1 &
ORCHESTRATOR_PID="$!"

ORCHESTRATOR_STARTUP_RESULT="started but readiness check failed"
for _ in $(seq 1 40); do
  if ! kill -0 "${ORCHESTRATOR_PID}" 2>/dev/null; then
    echo "Orchestrator failed to start. Log: ${ORCHESTRATOR_LOG_PATH}" >&2
    sed -n '1,160p' "${ORCHESTRATOR_LOG_PATH}" >&2 || true
    exit 1
  fi
  if curl -fsS "${ORCHESTRATOR_URL}/health" >/dev/null 2>&1; then
    ORCHESTRATOR_STARTUP_RESULT="ready"
    break
  fi
  sleep 0.25
done

PYTHONPATH="${UI_DIR}:${PYTHONPATH:-}" "${VENV_UVICORN}" eyeassist_gateway.app:app \
  --host "${HOST}" \
  --port "${PORT}" \
  --no-access-log \
  >"${LOG_PATH}" 2>&1 &
GATEWAY_PID="$!"

STARTUP_RESULT="started but readiness check failed"
for _ in $(seq 1 30); do
  if ! kill -0 "${GATEWAY_PID}" 2>/dev/null; then
    echo "Gateway failed to start. Log: ${LOG_PATH}" >&2
    sed -n '1,120p' "${LOG_PATH}" >&2 || true
    exit 1
  fi
  if curl -fsS "http://${HOST}:${PORT}/login" >/dev/null 2>&1; then
    STARTUP_RESULT="ready"
    break
  fi
  sleep 0.25
done

echo "EyeAssist rehearsal gateway PID: ${GATEWAY_PID}"
echo "Startup result: ${STARTUP_RESULT}"
echo "EyeAssist rehearsal orchestrator PID: ${ORCHESTRATOR_PID}"
echo "Orchestrator startup result: ${ORCHESTRATOR_STARTUP_RESULT}"
echo "URL: http://${HOST}:${PORT}"
echo "Orchestrator URL: ${ORCHESTRATOR_URL}"
echo "Ollama model: ${OLLAMA_MODEL}"
echo "Admin login: ${REHEARSAL_ADMIN_EMAIL} / ${REHEARSAL_ADMIN_PASSWORD}"
echo "Clinician login: ${REHEARSAL_CLINICIAN_EMAIL} / ${REHEARSAL_CLINICIAN_PASSWORD}"
echo "Runtime directory: ${RUNTIME_DIR}"
echo "Gateway log: ${LOG_PATH}"
echo "Orchestrator log: ${ORCHESTRATOR_LOG_PATH}"
echo "Press Ctrl-C to stop the rehearsal gateway."

wait "${GATEWAY_PID}"
