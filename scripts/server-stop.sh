#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_DIR="$ROOT/.run"

stop_pid() {
  local name="$1"
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
}

stop_pid frontend
stop_pid backend
