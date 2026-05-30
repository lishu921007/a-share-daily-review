#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_DIR="$ROOT/.run"

for name in backend frontend; do
  file="$PID_DIR/$name.pid"
  if [ -f "$file" ] && kill -0 "$(cat "$file")" 2>/dev/null; then
    echo "$name running pid=$(cat "$file")"
  else
    echo "$name stopped"
  fi
done

ss -ltnp | grep -E ':18081|:18082' || true
