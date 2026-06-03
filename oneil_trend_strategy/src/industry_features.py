from __future__ import annotations

import polars as pl


def add_industry_features(df: pl.DataFrame, logger) -> tuple[pl.DataFrame, bool]:
    if "industry_l1" not in df.columns or df["industry_l1"].null_count() == df.height:
        logger.warning("缺少 industry_l1，跳过行业过滤和行业统计。")
        return df.with_columns(pl.lit(None, dtype=pl.Float64).alias("industry_ret_20_rank_pct"), pl.lit(None, dtype=pl.Float64).alias("industry_ret_60_rank_pct")), False
    ind = df.group_by(["date", "industry_l1"]).agg(
        pl.col("ret_5").median().alias("industry_ret_5"),
        pl.col("ret_20").median().alias("industry_ret_20"),
        pl.col("ret_60").median().alias("industry_ret_60"),
        pl.len().alias("industry_stock_count"),
        pl.col("amount").sum().alias("industry_amount"),
    )
    ind = ind.with_columns(
        pl.col("industry_ret_20").rank("average").over("date").alias("_r20"),
        pl.col("industry_ret_60").rank("average").over("date").alias("_r60"),
        pl.count().over("date").alias("_n"),
    ).with_columns(
        (pl.col("_r20") / pl.col("_n")).alias("industry_ret_20_rank_pct"),
        (pl.col("_r60") / pl.col("_n")).alias("industry_ret_60_rank_pct"),
    ).drop(["_r20", "_r60", "_n"])
    out = df.join(ind, on=["date", "industry_l1"], how="left")
    logger.info("行业 L1 特征计算完成，行业数：%s", ind["industry_l1"].n_unique())
    return out, True
