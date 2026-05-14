@echo off
cd /d %~dp0\..
echo == A股每日复盘系统启动检查 ==
where python >nul 2>nul || (echo 缺少 Python，请先安装 & exit /b 1)
where npm >nul 2>nul || (echo 缺少 Node/npm，请先安装 Node.js & exit /b 1)
if not exist backend\.env (
  copy backend\.env.example backend\.env
  echo 缺少 backend\.env，已生成示例文件，请填写 TUSHARE_TOKEN 后重试。
  exit /b 1
)
if not exist data\universe\a_stock_universe.csv (echo 缺少 data\universe\a_stock_universe.csv & exit /b 1)
if not exist backend\.venv python -m venv backend\.venv
call backend\.venv\Scripts\activate
pip install -r backend\requirements.txt
cd frontend
if not exist node_modules npm install
start cmd /k "cd /d %~dp0\..\backend && ..\backend\.venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --port 8000"
start cmd /k "cd /d %~dp0\..\frontend && npm run dev"
echo 前端：http://127.0.0.1:5173
echo 后端：http://127.0.0.1:8000/api/health
