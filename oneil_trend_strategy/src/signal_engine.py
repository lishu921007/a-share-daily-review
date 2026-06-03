from __future__ import annotations

import polars as pl

from .pattern_signals import build_all_signals


def generate_signals(feature_df: pl.DataFrame, start_yyyymmdd: str, end_yyyymmdd: str, industry_enabled: bool, logger) -> pl.DataFrame:
    signals = build_all_signals(feature_df, industry_enabled, logger)
    if signals.height:
        signals = signals.filter((pl.col("date") >= start_yyyymmdd) & (pl.col("date") <= end_yyyymmdd))
    logger.info("验证区间内信号数：%s", signals.height)
    return signals
