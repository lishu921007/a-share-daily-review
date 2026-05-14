#!/usr/bin/env bash
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; TS=$(date +%Y%m%d_%H%M%S); OUT="$ROOT/backups/backup_$TS.tar.gz"
mkdir -p "$ROOT/backups"
tar -czf "$OUT" -C "$ROOT" data backend/.env 2>/dev/null || tar -czf "$OUT" -C "$ROOT" data
echo "备份完成：$OUT"
