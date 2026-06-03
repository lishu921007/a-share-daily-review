#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_PORT="${BACKEND_PORT:-18082}"
FRONTEND_PORT="${FRONTEND_PORT:-18081}"
PID_DIR="$ROOT/.run"
LOG_DIR="$ROOT/logs"

mkdir -p "$PID_DIR" "$LOG_DIR"

listener_pid() {
  local port="$1"
  ss -ltnp | awk -v p=":$port" '$4 ~ p {print $0}' | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | sort -u | head -n 1
}

wait_listener_pid() {
  local port="$1"
  local pid=""
  for _ in $(seq 1 20); do
    pid="$(listener_pid "$port" || true)"
    [ -n "$pid" ] && { echo "$pid"; return 0; }
    sleep 0.2
  done
  return 1
}

if [ -f "$PID_DIR/backend.pid" ] && kill -0 "$(cat "$PID_DIR/backend.pid")" 2>/dev/null; then
  echo "backend already running pid=$(cat "$PID_DIR/backend.pid")"
else
  cd "$ROOT/backend"
  [ -d .venv ] || python3 -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  nohup bash -c "exec uvicorn app.main:app --host 127.0.0.1 --port '$BACKEND_PORT'" > "$LOG_DIR/backend.log" 2>&1 &
  echo $! > "$PID_DIR/backend.pid"
  actual_pid="$(wait_listener_pid "$BACKEND_PORT" || true)"
  [ -n "$actual_pid" ] && echo "$actual_pid" > "$PID_DIR/backend.pid"
  echo "backend started pid=$(cat "$PID_DIR/backend.pid") port=$BACKEND_PORT"
fi

if [ -f "$PID_DIR/frontend.pid" ] && kill -0 "$(cat "$PID_DIR/frontend.pid")" 2>/dev/null; then
  echo "frontend already running pid=$(cat "$PID_DIR/frontend.pid")"
else
  cd "$ROOT/frontend"
  env VITE_PORT="$FRONTEND_PORT" VITE_API_PROXY="http://127.0.0.1:$BACKEND_PORT" npm run build
  nohup env VITE_PORT="$FRONTEND_PORT" VITE_API_PROXY="http://127.0.0.1:$BACKEND_PORT" ./node_modules/.bin/vite preview --host 0.0.0.0 --port "$FRONTEND_PORT" > "$LOG_DIR/frontend.log" 2>&1 &
  echo $! > "$PID_DIR/frontend.pid"
  actual_pid="$(wait_listener_pid "$FRONTEND_PORT" || true)"
  [ -n "$actual_pid" ] && echo "$actual_pid" > "$PID_DIR/frontend.pid"
  echo "frontend started pid=$(cat "$PID_DIR/frontend.pid") port=$FRONTEND_PORT"
fi

echo "frontend: http://0.0.0.0:$FRONTEND_PORT"
echo "backend health: http://127.0.0.1:$BACKEND_PORT/api/health"
