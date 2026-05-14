# A股每日复盘系统

一个本地可运行的 A 股每日复盘系统：使用 `a_stock_universe.csv` 作为股票池与行业分类基准，通过 Tushare 获取日 K、涨跌停与 moneyflow 数据，计算市场宽度、资金状态、行业共振，并提供前端展示。

## 技术栈

- 前端：React + Vite + TypeScript + Recharts
- 后端：FastAPI + pandas + tushare
- 缓存：Parquet/CSV 文件缓存
- 索引：SQLite

## 目录结构

```text
frontend/   前端页面
backend/    后端 API 与计算逻辑
data/       股票池、原始缓存、计算结果
scripts/    启动、备份、恢复脚本
docs/       拆解、口径、部署、操作文档
```

## 快速启动

```bash
cp backend/.env.example backend/.env
# 填写 backend/.env 中的 TUSHARE_TOKEN
scripts/start.sh
```

前端：http://127.0.0.1:5173  
后端：http://127.0.0.1:8000/api/health

## 配置

`backend/.env`：

```env
TUSHARE_TOKEN=你的Token
DATA_SOURCE=tushare
LOCAL_DATA_MODE=false
```

## 常见问题

1. **提示 Token 未配置**：检查 `backend/.env`。
2. **提示股票池不存在**：确认 `data/universe/a_stock_universe.csv` 存在。
3. **moneyflow 缺失**：可能是 Tushare 权限不足或当日数据未发布。
4. **指定日期不是交易日**：换成交易日，或先通过 `/api/trade/latest` 查询最近交易日。

## API

- `GET /api/health`
- `GET /api/trade/latest`
- `POST /api/review/update`
- `GET /api/review/daily?trade_date=YYYYMMDD`
- `GET /api/review/list?limit=60`
- `GET /api/review/trend?start_date=YYYYMMDD&end_date=YYYYMMDD`
- `GET /api/universe/info`
- `POST /api/universe/reload`
- `GET /api/limitup/review?end=YYYYMMDD&days=60`
- `POST /api/data/import`
