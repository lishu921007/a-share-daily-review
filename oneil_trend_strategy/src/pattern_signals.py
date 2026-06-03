from __future__ import annotations

import polars as pl

import config
from .feature_engineering import trend_filter_expr
from .weekly_filter import weekly_pattern_expr


SIGNAL_COLUMNS = [
    "date", "code", "industry_l1", "signal_type", "pivot_price", "close", "amount_ratio_20",
    "rs_20_rank_pct", "rs_60_rank_pct", "industry_ret_20_rank_pct", "pattern_quality_score",
    "signal_score", "pattern_detail", "weekly_filter_pass", "weekly_filter_mode", "weekly_pattern_ok",
    "weekly_trend_ok", "weekly_base_depth_30", "week_close_to_high_30", "week_close_to_high_52",
    "weekly_detail",
]


def _base(df: pl.DataFrame, signal_type: str, pivot: pl.Expr, detail: str, cond: pl.Expr, industry_enabled: bool) -> pl.DataFrame:
    q = config.PATTERN_QUALITY[signal_type]
    industry_rank = pl.col("industry_ret_20_rank_pct").fill_null(pl.col("rs_60_rank_pct"))
    if not industry_enabled:
        score = 0.50 * pl.col("rs_60_rank_pct") + 0.20 * pl.col("rs_20_rank_pct") + 0.15 * pl.col("amount_ratio_rank_pct") + 0.15 * pl.lit(q)
    else:
        score = 0.30 * pl.col("rs_60_rank_pct") + 0.20 * pl.col("rs_20_rank_pct") + 0.20 * industry_rank + 0.15 * pl.col("amount_ratio_rank_pct") + 0.15 * pl.lit(q)
    industry_filter = pl.lit(True) if not industry_enabled else (pl.col("industry_ret_20_rank_pct").fill_null(1.0) >= 0.30)
    use_weekly = config.USE_WEEKLY_FILTER and config.WEEKLY_FILTER_MODE != "off"
    weekly_pattern = weekly_pattern_expr(signal_type)
    weekly_filter = pl.col("weekly_filter_pass").fill_null(False) & weekly_pattern if use_weekly else pl.lit(True)
    weekly_detail = f"{config.WEEKLY_FILTER_MODE}: previous completed weekly bar + {signal_type} weekly structure"
    return (
        df.filter(pl.col("base_filter") & trend_filter_expr() & industry_filter & cond & weekly_filter)
        .with_columns(
            pl.lit(signal_type).alias("signal_type"),
            pivot.alias("pivot_price"),
            pl.lit(q).alias("pattern_quality_score"),
            score.clip(0, 3).alias("signal_score"),
            pl.lit(detail).alias("pattern_detail"),
            pl.col("weekly_filter_pass").fill_null(False).alias("weekly_filter_pass"),
            pl.lit(config.WEEKLY_FILTER_MODE if config.USE_WEEKLY_FILTER else "off").alias("weekly_filter_mode"),
            weekly_pattern.fill_null(False).alias("weekly_pattern_ok"),
            pl.col("weekly_trend_ok").fill_null(False).alias("weekly_trend_ok"),
            pl.col("week_base_depth_30").alias("weekly_base_depth_30"),
            pl.col("week_close_to_high_30").alias("week_close_to_high_30"),
            pl.col("week_close_to_high_52").alias("week_close_to_high_52"),
            pl.lit(weekly_detail if use_weekly else "weekly filter off; V1 daily-only mode").alias("weekly_detail"),
        )
        .select(SIGNAL_COLUMNS)
    )


def flat_base(df: pl.DataFrame, industry_enabled: bool) -> pl.DataFrame:
    cond = (
        ((pl.col("high_40_shift1") / pl.col("low_40_shift1") - 1) <= 0.15)
        & (pl.col("close") > pl.col("high_40_shift1"))
        & (pl.col("amount_ratio_20") >= 1.2)
        & (pl.col("pctChg") > 0.01)
        & ((pl.col("ret_60") >= 0.20) | (pl.col("rs_60_rank_pct") >= 0.70))
    )
    return _base(df, "flat_base", pl.col("high_40_shift1"), "40日窄平台突破，使用shift1平台高点", cond, industry_enabled)


def double_bottom(df: pl.DataFrame, industry_enabled: bool) -> pl.DataFrame:
    first_low = pl.col("low").shift(61).rolling_min(60, min_samples=45).over("code")
    second_low = pl.col("low").shift(1).rolling_min(60, min_samples=45).over("code")
    mid_high = pl.col("high").shift(30).rolling_max(60, min_samples=45).over("code")
    work = df.with_columns(first_low.alias("_first_low"), second_low.alias("_second_low"), mid_high.alias("_mid_high"))
    cond = (
        (pl.col("_second_low") <= pl.col("_first_low") * 1.03)
        & (pl.col("_second_low") >= pl.col("_first_low") * 0.85)
        & (pl.col("close") > pl.col("_mid_high"))
        & (pl.col("amount_ratio_20") >= 1.2)
        & (pl.col("pctChg") > 0.01)
    )
    return _base(work, "double_bottom", pl.col("_mid_high"), "120日窗口双底近似：前后60日低点+中段高点", cond, industry_enabled)


def cup_with_handle(df: pl.DataFrame, industry_enabled: bool) -> pl.DataFrame:
    cup_depth = pl.col("high_120_shift1") / pl.col("low_120_shift1") - 1
    handle_depth = pl.col("high_15_shift1") / pl.col("low_15_shift1") - 1
    cond = (
        (cup_depth >= 0.12) & (cup_depth <= 0.40)
        & (pl.col("close") >= pl.col("high_120_shift1") * 0.85)
        & (handle_depth <= 0.15)
        & (pl.col("low_15_shift1") > pl.col("low_120_shift1") + (pl.col("high_120_shift1") - pl.col("low_120_shift1")) * 0.5)
        & (pl.col("close") > pl.col("high_15_shift1"))
        & (pl.col("amount_ratio_20") >= 1.2)
        & (pl.col("pctChg") > 0.01)
    )
    return _base(df, "cup_with_handle", pl.col("high_15_shift1"), "120日杯体+15日把手近似突破", cond, industry_enabled)


def cup_without_handle(df: pl.DataFrame, industry_enabled: bool) -> pl.DataFrame:
    depth = pl.col("high_120_shift1") / pl.col("low_120_shift1") - 1
    cond = (depth >= 0.12) & (depth <= 0.45) & (pl.col("close") > pl.col("high_120_shift1")) & (pl.col("amount_ratio_20") >= 1.2) & (pl.col("close") > pl.col("ma20")) & (pl.col("ma20") >= pl.col("ma60") * 0.98)
    return _base(df, "cup_without_handle", pl.col("high_120_shift1"), "120日碟形底/无柄杯突破", cond, industry_enabled)


def base_on_base(df: pl.DataFrame, industry_enabled: bool) -> pl.DataFrame:
    prev_break = ((pl.col("close") > pl.col("high_60_shift1")).cast(pl.Int8).shift(1).rolling_max(80, min_samples=20).over("code") == 1)
    cond = prev_break & ((pl.col("high_30_shift1") / pl.col("low_30_shift1") - 1) <= 0.15) & (pl.col("close") > pl.col("high_30_shift1")) & (pl.col("amount_ratio_20") >= 1.2) & (pl.col("ret_80") < 1.0)
    return _base(df, "base_on_base", pl.col("high_30_shift1"), "80日内曾突破，最近30日小平台再突破", cond, industry_enabled)


def ascending_base(df: pl.DataFrame, industry_enabled: bool) -> pl.DataFrame:
    work = df.with_columns(
        pl.col("low").shift(61).rolling_min(30, min_samples=20).over("code").alias("_low1"),
        pl.col("low").shift(31).rolling_min(30, min_samples=20).over("code").alias("_low2"),
        pl.col("low").shift(1).rolling_min(30, min_samples=20).over("code").alias("_low3"),
        pl.col("high").shift(61).rolling_max(30, min_samples=20).over("code").alias("_high1"),
        pl.col("high").shift(31).rolling_max(30, min_samples=20).over("code").alias("_high2"),
        pl.col("high").shift(1).rolling_max(30, min_samples=20).over("code").alias("_high3"),
    )
    depth_ok = ((pl.col("_high1") / pl.col("_low1") - 1).is_between(0.06, 0.25)) & ((pl.col("_high2") / pl.col("_low2") - 1).is_between(0.06, 0.25)) & ((pl.col("_high3") / pl.col("_low3") - 1).is_between(0.06, 0.25))
    cond = (pl.col("_low1") < pl.col("_low2")) & (pl.col("_low2") < pl.col("_low3")) & (pl.col("_high1") < pl.col("_high2")) & (pl.col("_high2") < pl.col("_high3")) & depth_ok & (pl.col("close") > pl.col("_high3")) & (pl.col("amount_ratio_20") >= 1.2)
    return _base(work, "ascending_base", pl.col("_high3"), "90日三段式低点和高点抬高近似", cond, industry_enabled)


def high_tight_flag(df: pl.DataFrame, industry_enabled: bool) -> pl.DataFrame:
    cond = ((pl.col("high_60") / pl.col("low_60") - 1) >= 0.80) & ((pl.col("high_20") / pl.col("low_20") - 1) <= 0.25) & (pl.col("close") > pl.col("high_20_shift1")) & (pl.col("amount_ratio_20") >= 1.5)
    return _base(df, "high_tight_flag", pl.col("high_20_shift1"), "60日大涨后20日高位旗形突破，高风险单独统计", cond, industry_enabled)


def build_all_signals(df: pl.DataFrame, industry_enabled: bool, logger) -> pl.DataFrame:
    parts = [fn(df, industry_enabled) for fn in [flat_base, double_bottom, cup_with_handle, cup_without_handle, base_on_base, ascending_base, high_tight_flag]]
    out = pl.concat(parts, how="diagonal_relaxed") if parts else pl.DataFrame(schema=SIGNAL_COLUMNS)
    if out.height:
        out = out.sort(["date", "code", "signal_score"], descending=[False, False, True]).unique(subset=["date", "code"], keep="first")
    counts = out.group_by("signal_type").len().sort("signal_type") if out.height else pl.DataFrame({"signal_type": [], "len": []})
    logger.info("七类形态信号数量：%s", counts.to_dicts())
    return out
