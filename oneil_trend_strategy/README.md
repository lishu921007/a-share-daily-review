# 欧奈尔多形态趋势信号有效性验证系统

本项目是 A 股规则类趋势信号研究工具，不是实盘交易系统，也不是组合资金回测系统。它只做三件事：识别欧奈尔趋势类形态信号、按 `T+1 open` 验证后续收益、输出 CSV 明细和统计报告。

V1 是纯日 K 近似形态；V2 增加周 K 大结构过滤：周 K 判断大结构，日 K 判断突破买点，仍然用 `T+1 open` 做收益验证。欧奈尔形态本质上更强调中期整理结构，周 K 更适合过滤长期下降趋势和伪底部，日 K 则保留具体突破时点。

## 数据路径

- 日 K：`../data/raw/daily`
- 股票池：`../data/universe`
- 默认验证区间：`2024-01-01` 至 `2026-12-31`

日 K 会自动扫描 parquet/csv。当前父项目数据为按日期分文件的 Tushare parquet，字段映射在 `config.py` 中配置。

## 安装与运行

```bash
cd /root/.openclaw/workspace/projects/a-share-daily-review/oneil_trend_strategy
../backend/.venv/bin/python -m pip install -r requirements.txt
../backend/.venv/bin/python run_signal_validation.py
```

也可以显式指定路径：

```bash
../backend/.venv/bin/python run_signal_validation.py \
  --daily_dir ../data/raw/daily \
  --universe_dir ../data/universe \
  --start_date 2024-01-01 \
  --end_date 2026-12-31 \
  --output_dir outputs
```

V1/V2 对比运行：

```bash
../backend/.venv/bin/python run_signal_validation.py \
  --daily_dir ../data/raw/daily \
  --universe_dir ../data/universe \
  --start_date 2024-01-01 \
  --end_date 2026-06-01 \
  --output_dir outputs \
  --compare_v1_v2
```

双形态卖点敏感性深挖：

```bash
../backend/.venv/bin/python run_pattern_deep_dive.py \
  --daily_dir ../data/raw/daily \
  --universe_dir ../data/universe \
  --start_date 2024-01-01 \
  --end_date 2026-06-01 \
  --output_dir outputs
```

该脚本不重新生成形态信号，不覆盖 V1/V2 输出；它读取最新 `signals_*_v2_weekly_loose.csv`，只针对 `base_on_base` 和 `cup_with_handle` 重新计算不同卖点规则下的 `trend_return`，输出到 `outputs/deep_dive/`。

`base_on_base` 主线策略实验：

```bash
../backend/.venv/bin/python run_base_on_base_strategy_lab.py \
  --daily_dir ../data/raw/daily \
  --universe_dir ../data/universe \
  --start_date 2024-01-01 \
  --end_date 2026-06-01 \
  --output_dir outputs
```

该脚本读取最新 V2 周线过滤信号，只研究 `base_on_base`。它会补充第二平台深度、突破幅度等字段，对买点过滤和卖点规则做参数网格，并按中位真实收益、胜率、右尾、左尾和回撤综合评分，输出到 `outputs/base_on_base_lab/`。

## 形态信号

第一版实现 7 类日线近似形态：

- `flat_base`：平底突破
- `double_bottom`：双底突破
- `cup_with_handle`：杯柄突破
- `cup_without_handle`：无柄杯 / 碟形底突破
- `base_on_base`：底上底
- `ascending_base`：上升底
- `high_tight_flag`：高紧旗

V2 已实现周 K 构造、周线特征、周线过滤和按形态的周线辅助判断。当前周线过滤默认使用上一根完整周 K，属于保守实现：周一到周五的日线信号都只看上一周已经完成的周 K，不使用本周未完成结构。

## 收益口径

每个信号都是独立样本：

- `signal_date`：T 日收盘确认信号
- `entry_date`：T+1 交易日
- `entry_price`：T+1 open
- 固定持有收益：`ret_1d_open`、`ret_2d_open`、`ret_3d_open`、`ret_5d_open`、`ret_10d_open`、`ret_20d_open`、`ret_40d_open`、`ret_60d_open`
- 趋势卖出收益：按收盘触发，下一交易日 open 卖出

## 输出文件

- `outputs/signals/signals_YYYYMMDD_HHMMSS.csv`
- `outputs/validation/signal_validation_YYYYMMDD_HHMMSS.csv`
- `outputs/stats/summary_YYYYMMDD_HHMMSS.csv`
- `outputs/stats/by_signal_type_YYYYMMDD_HHMMSS.csv`
- `outputs/stats/by_industry_YYYYMMDD_HHMMSS.csv`
- `outputs/stats/by_year_YYYYMMDD_HHMMSS.csv`
- `outputs/stats/by_weekly_filter_pass_YYYYMMDD_HHMMSS.csv`
- `outputs/stats/by_signal_type_weekly_YYYYMMDD_HHMMSS.csv`
- `outputs/stats/v1_v2_compare_YYYYMMDD_HHMMSS.csv`
- `outputs/stats/return_distribution_YYYYMMDD_HHMMSS.csv`
- `outputs/deep_dive/exit_sensitivity_summary_YYYYMMDD_HHMMSS.csv`
- `outputs/deep_dive/exit_reason_summary_YYYYMMDD_HHMMSS.csv`
- `outputs/deep_dive/trend_return_quantiles_YYYYMMDD_HHMMSS.csv`
- `outputs/base_on_base_lab/base_on_base_strategy_grid_YYYYMMDD_HHMMSS.csv`
- `outputs/base_on_base_lab/base_on_base_top20_YYYYMMDD_HHMMSS.csv`
- `outputs/base_on_base_lab/base_on_base_top5_by_year_YYYYMMDD_HHMMSS.csv`
- `outputs/base_on_base_lab/base_on_base_top5_exit_reasons_YYYYMMDD_HHMMSS.csv`

判断信号是否有效，应重点看各形态的样本数、`ret_10d/20d/40d` 均值和中位数、胜率、趋势卖出收益分布，而不是单次最大收益。
