# 数据目录说明

## 股票池

- `data/universe/a_stock_universe.csv`
- 当前识别字段：
  - 股票代码：`code`
  - 股票名称：`code_name`
  - 行业字段：`industry_L2_name`
  - 剔除字段：`if_out`

## 原始数据

原始数据只放接口拉取并按股票池过滤后的数据，不放计算结果。

- `data/raw/daily/YYYYMMDD.parquet`
  - 日线数据
  - 主要字段：`ts_code, trade_date, open, high, low, close, pre_close, change, pct_chg, vol, amount`
- `data/raw/moneyflow/YYYYMMDD.parquet`
  - 资金流数据
  - 主要字段：`ts_code, trade_date, buy_*_amount, sell_*_amount, net_mf_amount`
- `data/raw/stk_limit/YYYYMMDD.parquet`
  - 涨跌停价格数据，如后续复盘计算需要再补充

## 计算结果

计算结果和原始数据分开存放。

- `data/processed/review/YYYYMMDD.json`
  - 每日复盘计算结果
- `data/cache/review_index.sqlite3`
  - 复盘结果索引缓存
- `data/cache/limitup_review_tushare/`
  - 涨停复盘缓存
- `data/cache/strong_trend_tushare/`
  - 强趋势计算缓存

## 下载清单

- `data/manifests/recent_300d_download_latest.json`
  - 最近一次批量下载清单
  - 记录交易日、daily 行数、moneyflow 行数、失败原因、目录说明
- `data/manifests/recent_300d_download_YYYYMMDD_HHMMSS.json`
  - 历史批量下载清单快照

## 本次初始化结果

- 成功落盘交易日：300 个
- 成功日期范围：`20250303` 至 `20260527`
- `daily` 文件数：300
- `moneyflow` 文件数：300
- `20260528` 未纳入成功数据：Tushare 当日 daily/moneyflow 尚未发布或接口暂不可取，已在 manifest 标记，不造假数据。
