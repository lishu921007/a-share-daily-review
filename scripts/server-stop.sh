#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_DIR="$ROOT/.run"

stop_pid() {
  local name="$1"
  local port="$2"
  local file="$PID_DIR/$name.pid"
  if [ -f "$file" ]; then
    local pid
    pid="$(cat "$file")"
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid"
      echo "stopped $name pid=$pid"
    else
      echo "$name not running"
    fi
    rm -f "$file"
  else
    echo "$name pid file not found"
  fi

  local pids
  pids="$(ss -ltnp | awk -v p=":$port" '$4 ~ p {print $0}' | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | sort -u)"
  for pid in $pids; do
    local cmd
    cmd="$(ps -p "$pid" -o cmd= 2>/dev/null || true)"
    case "$cmd" in
      *a-share-daily-review*|*vite*)
        kill "$pid"
        echo "stopped $name listener pid=$pid port=$port"
        ;;
    esac
  done
}

stop_pid frontend "${FRONTEND_PORT:-18081}"
stop_pid backend "${BACKEND_PORT:-18082}"
