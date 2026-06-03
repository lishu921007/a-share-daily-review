from __future__ import annotations

import polars as pl

import config


def add_weekly_filter_columns(df: pl.DataFrame, mode: str | None = None) -> pl.DataFrame:
    mode = mode or config.WEEKLY_FILTER_MODE
    if mode == "off":
        weekly_trend = pl.lit(True)
    elif mode == "strict":
        weekly_trend = (
            (pl.col("week_close") > pl.col("week_ma10"))
            & (pl.col("week_ma10") >= pl.col("week_ma30"))
            & (pl.col("week_ma10_slope_3") >= 0)
            & (pl.col("week_base_depth_30") >= 0.10)
            & (pl.col("week_base_depth_30") <= 0.35)
            & (pl.col("week_close_to_high_30") >= 0.85)
            & (pl.col("week_close_to_high_52") >= 0.70)
            & ((pl.col("week_ret_26") >= 0) | (pl.col("week_close_to_high_52") >= 0.80))
        )
    else:
        weekly_trend = (
            (pl.col("week_close") > pl.col("week_ma10") * 0.95)
            & (pl.col("week_ma10") >= pl.col("week_ma30") * 0.95)
            & (pl.col("week_base_depth_30") >= 0.08)
            & (pl.col("week_base_depth_30") <= 0.45)
            & (pl.col("week_close_to_high_30") >= 0.75)
            & (pl.col("week_close_to_high_52") >= 0.60)
            & (pl.col("week_amount_ma10") > 0)
        )
    return df.with_columns(
        weekly_trend.fill_null(False).alias("weekly_trend_ok"),
        ((pl.col("week_base_depth_8") <= 0.20) & (pl.col("week_close_to_high_13") >= 0.80) & (pl.col("week_close") > pl.col("week_ma10") * 0.95)).fill_null(False).alias("weekly_flat_ok"),
        ((pl.col("week_base_depth_26") >= 0.12) & (pl.col("week_base_depth_26") <= 0.45) & (pl.col("week_close_to_high_26") >= 0.70) & (pl.col("week_close") > pl.col("week_ma10") * 0.90)).fill_null(False).alias("weekly_double_bottom_ok"),
        ((pl.col("week_base_depth_26") >= 0.12) & (pl.col("week_base_depth_26") <= 0.45) & (pl.col("week_close_to_high_26") >= 0.75) & (pl.col("week_close") > pl.col("week_ma10") * 0.90)).fill_null(False).alias("weekly_cup_ok"),
        ((pl.col("week_base_depth_30") >= 0.12) & (pl.col("week_base_depth_30") <= 0.50) & (pl.col("week_close_to_high_30") >= 0.80)).fill_null(False).alias("weekly_saucer_ok"),
        ((pl.col("week_close_to_high_26") >= 0.75) & (pl.col("week_base_depth_13") <= 0.30) & (pl.col("week_close") > pl.col("week_ma10") * 0.95)).fill_null(False).alias("weekly_base_on_base_ok"),
        ((pl.col("week_ma10") >= pl.col("week_ma30") * 0.95) & (pl.col("week_close_to_high_26") >= 0.75) & (pl.col("week_ret_13") > -0.10)).fill_null(False).alias("weekly_ascending_ok"),
        (((pl.col("week_ret_8") >= 0.40) | (pl.col("week_ret_13") >= 0.60)) & (pl.col("week_base_depth_8") <= 0.30) & (pl.col("week_close_to_high_13") >= 0.85)).fill_null(False).alias("weekly_high_tight_ok"),
    ).with_columns(pl.col("weekly_trend_ok").alias("weekly_filter_pass"))


def weekly_pattern_expr(signal_type: str) -> pl.Expr:
    mapping = {
        "flat_base": "weekly_flat_ok",
        "double_bottom": "weekly_double_bottom_ok",
        "cup_with_handle": "weekly_cup_ok",
        "cup_without_handle": "weekly_saucer_ok",
        "base_on_base": "weekly_base_on_base_ok",
        "ascending_base": "weekly_ascending_ok",
        "high_tight_flag": "weekly_high_tight_ok",
    }
    return pl.col(mapping[signal_type]).fill_null(False)
