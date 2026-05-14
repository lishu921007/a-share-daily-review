#!/usr/bin/env bash
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
echo "== A股每日复盘系统启动检查 =="
command -v python3 >/dev/null || { echo "缺少 Python3，请先安装。"; exit 1; }
command -v npm >/dev/null || { echo "缺少 Node/npm，请先安装 Node.js。"; exit 1; }
[ -f backend/.env ] || { echo "缺少 backend/.env，请先复制 backend/.env.example 并填写 TUSHARE_TOKEN。"; cp -n backend/.env.example backend/.env; exit 1; }
grep -q '^TUSHARE_TOKEN=请填写' backend/.env && { echo "backend/.env 中 TUSHARE_TOKEN 尚未填写。"; exit 1; }
[ -f data/universe/a_stock_universe.csv ] || { echo "缺少 data/universe/a_stock_universe.csv。"; exit 1; }
if [ ! -d backend/.venv ]; then python3 -m venv backend/.venv; fi
source backend/.venv/bin/activate
pip install -r backend/requirements.txt
if [ ! -d frontend/node_modules ]; then (cd frontend && npm install); fi
trap 'kill 0' EXIT
(cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000) &
(cd frontend && npm run dev) &
echo "后端：http://127.0.0.1:8000/api/health"
echo "前端：http://127.0.0.1:5173"
wait
