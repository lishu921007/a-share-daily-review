#!/usr/bin/env bash
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ -n "$1" ] || { echo "用法：scripts/restore.sh backups/backup_xxx.tar.gz"; exit 1; }
[ -f "$1" ] || { echo "备份文件不存在：$1"; exit 1; }
SAFE="$ROOT/backups/pre_restore_$(date +%Y%m%d_%H%M%S).tar.gz"; mkdir -p "$ROOT/backups"
tar -czf "$SAFE" -C "$ROOT" data backend/.env 2>/dev/null || true
tar -xzf "$1" -C "$ROOT"
echo "恢复完成。恢复前备份：$SAFE"
