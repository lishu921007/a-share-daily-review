from __future__ import annotations

import polars as pl

import config


def add_daily_features(df: pl.DataFrame, logger) -> pl.DataFrame:
    df = df.sort(["code", "date"])
    if df["pctChg"].null_count() > 0:
        df = df.with_columns(
            pl.when(pl.col("pctChg").is_null() & pl.col("pre_close").is_not_null() & (pl.col("pre_close") > 0))
            .then(pl.col("close") / pl.col("pre_close") - 1)
            .when(pl.col("pctChg").abs() > 1.0)
            .then(pl.col("pctChg") / 100.0)
            .otherwise(pl.col("pctChg"))
            .alias("pctChg")
        )
    else:
        df = df.with_columns(
            pl.when(pl.col("pctChg").abs() > 1.0).then(pl.col("pctChg") / 100.0).otherwise(pl.col("pctChg")).alias("pctChg")
        )

    exprs = []
    for w in [5, 10, 20, 60, 120]:
        exprs.append(pl.col("close").rolling_mean(w, min_samples=w).over("code").alias(f"ma{w}"))
    for w in [5, 10, 20, 60]:
        exprs.append(pl.col("amount").rolling_mean(w, min_samples=w).over("code").alias(f"amount_ma{w}"))
    for w in [5, 10, 20, 60, 80, 120]:
        exprs.append((pl.col("close") / pl.col("close").shift(w).over("code") - 1).alias(f"ret_{w}"))
    for w in [15, 20, 30, 40, 60, 90, 120, 150, 250]:
        hi = pl.col("high").rolling_max(w, min_samples=w).over("code")
        lo = pl.col("low").rolling_min(w, min_samples=w).over("code")
        exprs.extend([hi.alias(f"high_{w}"), lo.alias(f"low_{w}"), hi.shift(1).over("code").alias(f"high_{w}_shift1"), lo.shift(1).over("code").alias(f"low_{w}_shift1")])
    df = df.with_columns(exprs)
    df = df.with_columns(
        (pl.col("amount") / pl.col("amount_ma20")).alias("amount_ratio_20"),
        (pl.col("amount") / pl.col("amount_ma60")).alias("amount_ratio_60"),
        (pl.col("close") / pl.col("high_60")).alias("close_to_high_60"),
        (pl.col("close") / pl.col("high_120")).alias("close_to_high_120"),
        (pl.col("close") / pl.col("high_250")).alias("close_to_high_250"),
        (pl.col("close") / pl.col("low_60")).alias("close_to_low_60"),
        (pl.col("close") / pl.col("low_120")).alias("close_to_low_120"),
        (pl.col("ma20") / pl.col("ma20").shift(5).over("code") - 1).alias("ma20_slope_5"),
        (pl.col("ma60") / pl.col("ma60").shift(10).over("code") - 1).alias("ma60_slope_10"),
    )
    df = df.with_columns(
        pl.col("ret_20").rank("average").over("date").alias("_rs20_rank"),
        pl.col("ret_60").rank("average").over("date").alias("_rs60_rank"),
        pl.col("ret_120").rank("average").over("date").alias("_rs120_rank"),
        pl.col("amount_ratio_20").rank("average").over("date").alias("_amount_rank"),
        pl.count().over("date").alias("_date_count"),
    ).with_columns(
        (pl.col("_rs20_rank") / pl.col("_date_count")).alias("rs_20_rank_pct"),
        (pl.col("_rs60_rank") / pl.col("_date_count")).alias("rs_60_rank_pct"),
        (pl.col("_rs120_rank") / pl.col("_date_count")).alias("rs_120_rank_pct"),
        (pl.col("_amount_rank") / pl.col("_date_count")).alias("amount_ratio_rank_pct"),
    ).drop(["_rs20_rank", "_rs60_rank", "_rs120_rank", "_amount_rank", "_date_count"])

    df = df.with_columns(
        (
            (pl.col("tradestatus") == "1")
            & (pl.col("isST") == "0")
            & (pl.col("amount_ma20") >= config.AMOUNT_MIN_YUAN)
            & pl.all_horizontal([pl.col(c).is_not_null() for c in ["open", "high", "low", "close", "amount"]])
            & (pl.col("close") > 3)
            & (pl.col("amount") > 0)
        ).alias("base_filter")
    )
    logger.info("基础日线特征计算完成，行数：%s", df.height)
    return df


def trend_filter_expr() -> pl.Expr:
    if config.TREND_FILTER_MODE == "strict":
        return (
            (pl.col("close") > pl.col("ma20"))
            & (pl.col("ma20") > pl.col("ma60"))
            & (pl.col("ma20_slope_5") > 0)
            & (pl.col("close") >= pl.col("high_120") * 0.85)
            & (pl.col("rs_60_rank_pct") >= 0.70)
            & (pl.col("amount_ratio_20") >= 1.2)
        )
    return (
        (pl.col("close") > pl.col("ma20"))
        & (pl.col("ma20") >= pl.col("ma60") * 0.98)
        & (pl.col("close") >= pl.col("high_120") * 0.75)
        & (pl.col("rs_60_rank_pct") >= 0.50)
        & (pl.col("amount_ma20") >= config.AMOUNT_MIN_YUAN)
        & (pl.col("amount_ratio_20") >= 1.0)
    )
