from __future__ import annotations

import polars as pl


def build_weekly_bars(df: pl.DataFrame) -> pl.DataFrame:
    """Build completed natural-week bars from daily bars."""
    return (
        df.with_columns(pl.col("date").str.strptime(pl.Date, "%Y%m%d").alias("_dt"))
        .with_columns(
            pl.col("_dt").dt.strftime("%G%V").alias("_week"),
            pl.col("_dt").dt.truncate("1w").dt.strftime("%Y%m%d").alias("week_start_date"),
        )
        .sort(["code", "date"])
        .group_by(["code", "_week", "week_start_date"])
        .agg(
            pl.col("date").last().alias("week_end_date"),
            pl.col("open").first().alias("week_open"),
            pl.col("high").max().alias("week_high"),
            pl.col("low").min().alias("week_low"),
            pl.col("close").last().alias("week_close"),
            pl.col("amount").sum().alias("week_amount"),
            pl.col("industry_l1").drop_nulls().last().alias("industry_l1"),
        )
        .sort(["code", "week_start_date"])
        .drop("_week")
    )
