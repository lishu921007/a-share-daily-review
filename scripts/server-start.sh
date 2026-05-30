#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_PORT="${BACKEND_PORT:-18082}"
FRONTEND_PORT="${FRONTEND_PORT:-18081}"
PID_DIR="$ROOT/.run"
LOG_DIR="$ROOT/logs"

mkdir -p "$PID_DIR" "$LOG_DIR"

if [ -f "$PID_DIR/backend.pid" ] && kill -0 "$(cat "$PID_DIR/backend.pid")" 2>/dev/null; then
  echo "backend already running pid=$(cat "$PID_DIR/backend.pid")"
else
  cd "$ROOT/backend"
  [ -d .venv ] || python3 -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  nohup uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT" > "$LOG_DIR/backend.log" 2>&1 &
  echo $! > "$PID_DIR/backend.pid"
  echo "backend started pid=$(cat "$PID_DIR/backend.pid") port=$BACKEND_PORT"
fi

if [ -f "$PID_DIR/frontend.pid" ] && kill -0 "$(cat "$PID_DIR/frontend.pid")" 2>/dev/null; then
  echo "frontend already running pid=$(cat "$PID_DIR/frontend.pid")"
else
  cd "$ROOT/frontend"
  nohup env VITE_PORT="$FRONTEND_PORT" VITE_API_PROXY="http://127.0.0.1:$BACKEND_PORT" npm run dev > "$LOG_DIR/frontend.log" 2>&1 &
  echo $! > "$PID_DIR/frontend.pid"
  echo "frontend started pid=$(cat "$PID_DIR/frontend.pid") port=$FRONTEND_PORT"
fi

echo "frontend: http://0.0.0.0:$FRONTEND_PORT"
echo "backend health: http://127.0.0.1:$BACKEND_PORT/api/health"
