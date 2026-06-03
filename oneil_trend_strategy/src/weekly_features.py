from __future__ import annotations

import polars as pl

from .weekly_builder import build_weekly_bars


def add_weekly_features(daily_df: pl.DataFrame, logger) -> pl.DataFrame:
    weekly = build_weekly_bars(daily_df)
    exprs = []
    for w in [5, 10, 20, 30, 40]:
        exprs.append(pl.col("week_close").rolling_mean(w, min_samples=w).over("code").alias(f"week_ma{w}"))
    for w in [5, 10, 20]:
        exprs.append(pl.col("week_amount").rolling_mean(w, min_samples=w).over("code").alias(f"week_amount_ma{w}"))
    for w in [4, 8, 13, 26]:
        exprs.append((pl.col("week_close") / pl.col("week_close").shift(w).over("code") - 1).alias(f"week_ret_{w}"))
    for w in [8, 13, 26, 30, 40, 52]:
        hi = pl.col("week_high").rolling_max(w, min_samples=w).over("code")
        lo = pl.col("week_low").rolling_min(w, min_samples=w).over("code")
        exprs.extend([
            hi.alias(f"week_high_{w}"),
            lo.alias(f"week_low_{w}"),
            hi.shift(1).over("code").alias(f"week_high_{w}_shift1"),
        ])
    weekly = weekly.with_columns(exprs)
    weekly = weekly.with_columns(
        (pl.col("week_close") / pl.col("week_high_26")).alias("week_close_to_high_26"),
        (pl.col("week_close") / pl.col("week_high_13")).alias("week_close_to_high_13"),
        (pl.col("week_close") / pl.col("week_high_30")).alias("week_close_to_high_30"),
        (pl.col("week_close") / pl.col("week_high_52")).alias("week_close_to_high_52"),
        (pl.col("week_close") / pl.col("week_low_26")).alias("week_close_to_low_26"),
        (pl.col("week_high_8") / pl.col("week_low_8") - 1).alias("week_base_depth_8"),
        (pl.col("week_high_13") / pl.col("week_low_13") - 1).alias("week_base_depth_13"),
        (pl.col("week_high_26") / pl.col("week_low_26") - 1).alias("week_base_depth_26"),
        (pl.col("week_high_30") / pl.col("week_low_30") - 1).alias("week_base_depth_30"),
        (pl.col("week_high_40") / pl.col("week_low_40") - 1).alias("week_base_depth_40"),
        (pl.col("week_ma10") / pl.col("week_ma10").shift(3).over("code") - 1).alias("week_ma10_slope_3"),
        (pl.col("week_ma30") / pl.col("week_ma30").shift(5).over("code") - 1).alias("week_ma30_slope_5"),
    )
    weekly = weekly.with_columns(
        pl.col("week_start_date").shift(-1).over("code").alias("weekly_effective_from")
    )
    logger.info("周 K 特征计算完成，周线行数：%s", weekly.height)
    return weekly


def join_weekly_features_to_daily(daily_df: pl.DataFrame, weekly_df: pl.DataFrame, logger) -> pl.DataFrame:
    feature_cols = [
        "code", "weekly_effective_from", "week_start_date", "week_end_date", "week_close", "week_amount_ma10",
        "week_ma10", "week_ma30", "week_ret_8", "week_ret_13", "week_ret_26",
        "week_close_to_high_13", "week_close_to_high_26", "week_close_to_high_30", "week_close_to_high_52",
        "week_base_depth_8", "week_base_depth_13", "week_base_depth_26", "week_base_depth_30", "week_base_depth_40",
        "week_ma10_slope_3", "week_ma30_slope_5",
    ]
    existing = [c for c in feature_cols if c in weekly_df.columns]
    weekly = weekly_df.filter(pl.col("weekly_effective_from").is_not_null()).select(existing).sort(["code", "weekly_effective_from"])
    joined = daily_df.sort(["code", "date"]).join_asof(
        weekly,
        left_on="date",
        right_on="weekly_effective_from",
        by="code",
        strategy="backward",
    )
    logger.info("周线特征已按上一根完整周 K 映射回日线。")
    return joined
