# 策略规则说明

本项目只验证趋势形态信号有效性，不做资金曲线、仓位管理、下单和组合回测。

## 基础过滤

- `tradestatus == 1`
- 非 ST：如有 `isST` 字段，要求 `isST == 0`
- 最近 20 日平均成交额不低于 5000 万元
- `open/high/low/close/amount` 非空
- `close > 3`
- `amount > 0`
- 股票代码在 `data/universe` 股票池内

## 趋势过滤

默认宽松过滤：

- `close > ma20`
- `ma20 >= ma60 * 0.98`
- `close >= high_120 * 0.75`
- `rs_60_rank_pct >= 0.50`
- `amount_ma20 >= 50_000_000`
- `amount_ratio_20 >= 1.0`

## 行业过滤

如果存在 `industry_l1`，剔除 `industry_ret_20_rank_pct < 0.30` 的行业；如果不存在行业字段，则跳过行业过滤并记录日志。

## 七类形态

七类形态均在 T 日收盘确认，突破高点使用 `shift1` 历史高点，避免把当天高点作为突破基准。`double_bottom`、`cup_with_handle`、`ascending_base` 当前为日线窗口近似量化。

## 周 K 大结构过滤

配置项：

- `USE_WEEKLY_FILTER = True`
- `WEEKLY_FILTER_MODE = "loose"`
- 可选模式：`off`、`loose`、`strict`

V2 默认采用上一根完整周 K 映射到日线，保证周中信号不使用本周未完成周线。

`loose` 模式：

- `week_close > week_ma10 * 0.95`
- `week_ma10 >= week_ma30 * 0.95`
- `0.08 <= week_base_depth_30 <= 0.45`
- `week_close_to_high_30 >= 0.75`
- `week_close_to_high_52 >= 0.60`
- `week_amount_ma10 > 0`

`strict` 模式预留并已实现：

- `week_close > week_ma10`
- `week_ma10 >= week_ma30`
- `week_ma10_slope_3 >= 0`
- `0.10 <= week_base_depth_30 <= 0.35`
- `week_close_to_high_30 >= 0.85`
- `week_close_to_high_52 >= 0.70`
- `week_ret_26 >= 0` 或 `week_close_to_high_52 >= 0.80`

按形态周线辅助判断：

- `flat_base`：`weekly_flat_ok`
- `double_bottom`：`weekly_double_bottom_ok`
- `cup_with_handle`：`weekly_cup_ok`
- `cup_without_handle`：`weekly_saucer_ok`
- `base_on_base`：`weekly_base_on_base_ok`
- `ascending_base`：`weekly_ascending_ok`
- `high_tight_flag`：`weekly_high_tight_ok`

当 `USE_WEEKLY_FILTER = True` 时，最终信号必须同时满足日线形态、`weekly_filter_pass` 和对应形态的 `weekly_xxx_ok`。当 `WEEKLY_FILTER_MODE = "off"` 或关闭周线过滤时，保持 V1 纯日线逻辑。

## V1/V2 对比口径

`--compare_v1_v2` 会在同一批日线和股票池上分别运行：

- V1：`USE_WEEKLY_FILTER = False`
- V2：`USE_WEEKLY_FILTER = True` 且 `WEEKLY_FILTER_MODE = "loose"`

对比文件输出到 `outputs/stats/v1_v2_compare_YYYYMMDD_HHMMSS.csv`，用于观察信号数量、均值、中位数、胜率和趋势卖出收益变化。

## 入场与收益

- 入场：T+1 open
- 固定周期收益：从 T+1 open 到后续第 N 个交易日 open
- 趋势卖出：某日收盘触发卖出条件，下一交易日 open 卖出

## signal_score

默认由相对强度、行业强度、成交额放大排名、形态质量分构成。没有行业字段时，行业权重分配给 `rs_60_rank_pct`。
