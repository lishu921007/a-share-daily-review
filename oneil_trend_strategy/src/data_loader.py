from __future__ import annotations

from pathlib import Path
import polars as pl

import config
from .utils import normalize_code, normalize_date


def _first_existing(cols: list[str], candidates: list[str]) -> str | None:
    for c in candidates:
        if c in cols:
            return c
    return None


def load_universe(universe_dir: Path, logger) -> pl.DataFrame:
    files = sorted(list(universe_dir.glob("*.csv")) + list(universe_dir.glob("*.parquet")))
    if not files:
        raise FileNotFoundError(f"股票池目录没有 csv/parquet 文件：{universe_dir}")
    path = files[0]
    df = pl.read_parquet(path) if path.suffix == ".parquet" else pl.read_csv(path, infer_schema_length=2000)
    cols = df.columns
    code_col = _first_existing(cols, config.UNIVERSE_CODE_CANDIDATES)
    if not code_col:
        raise ValueError(f"股票池无法识别代码字段，当前字段：{cols}")
    industry_col = _first_existing(cols, config.UNIVERSE_INDUSTRY_CANDIDATES)
    if "if_out" in cols:
        df = df.filter(pl.col("if_out").cast(pl.Int64, strict=False).fill_null(1) == 0)
    out = df.select(pl.col(code_col).cast(pl.Utf8).map_elements(normalize_code, return_dtype=pl.Utf8).alias("code"))
    if industry_col:
        out = out.with_columns(df.select(pl.col(industry_col).cast(pl.Utf8)).to_series().alias("industry_l1"))
    else:
        out = out.with_columns(pl.lit(None, dtype=pl.Utf8).alias("industry_l1"))
        logger.warning("股票池没有 industry_l1 字段，行业统计将跳过。")
    out = out.unique(subset=["code"])
    logger.info("股票池：%s，纳入股票 %s 只", path, out.height)
    return out


def detect_daily_files(daily_dir: Path) -> list[Path]:
    parquet = sorted(daily_dir.glob("*.parquet"))
    csv = sorted(daily_dir.glob("*.csv"))
    return parquet if parquet else csv


def _add_hfq_prices(df: pl.DataFrame, logger) -> pl.DataFrame:
    if config.PRICE_ADJUST_MODE == "raw":
        return df.with_columns(
            pl.lit("raw").alias("price_adjust_mode"),
            pl.lit(1.0).alias("hfq_factor"),
            pl.lit(False).alias("suspect_ex_dividend"),
        )
    if config.PRICE_ADJUST_MODE != "hfq":
        raise ValueError(f"不支持的 PRICE_ADJUST_MODE：{config.PRICE_ADJUST_MODE}")
    if df["pre_close"].null_count() > 0:
        raise ValueError("PRICE_ADJUST_MODE='hfq' 需要 pre_close 字段完整，当前存在空值。")
    df = df.sort(["code", "date"])
    prev_close = pl.col("close").shift(1).over("code")
    ratio = (
        pl.when(prev_close.is_not_null() & pl.col("pre_close").is_not_null() & (pl.col("pre_close") > 0))
        .then(prev_close / pl.col("pre_close"))
        .otherwise(1.0)
        .clip(0.2, 5.0)
    )
    df = df.with_columns(
        pl.col("open").alias("open_raw"),
        pl.col("high").alias("high_raw"),
        pl.col("low").alias("low_raw"),
        pl.col("close").alias("close_raw"),
        ratio.alias("_hfq_ratio"),
        ((ratio - 1).abs() > 0.005).alias("suspect_ex_dividend"),
    )
    df = df.with_columns(
        pl.col("_hfq_ratio").cum_prod().over("code").alias("hfq_factor")
    ).with_columns(
        (pl.col("open_raw") * pl.col("hfq_factor")).alias("open"),
        (pl.col("high_raw") * pl.col("hfq_factor")).alias("high"),
        (pl.col("low_raw") * pl.col("hfq_factor")).alias("low"),
        (pl.col("close_raw") * pl.col("hfq_factor")).alias("close"),
        pl.lit("hfq").alias("price_adjust_mode"),
    ).drop("_hfq_ratio")
    logger.info(
        "后复权价格构造完成：疑似除权/复权跳变行数=%s，股票数=%s",
        df.filter(pl.col("suspect_ex_dividend")).height,
        df.filter(pl.col("suspect_ex_dividend"))["code"].n_unique(),
    )
    return df


def load_daily_data(daily_dir: Path, universe: pl.DataFrame, start_date: str, end_date: str, logger) -> pl.DataFrame:
    files = detect_daily_files(daily_dir)
    if not files:
        raise FileNotFoundError(f"日 K 目录没有 parquet/csv 文件：{daily_dir}")
    logger.info("日 K 文件数：%s，优先格式：%s", len(files), files[0].suffix)
    frames = []
    for path in files:
        stem = path.stem
        if stem.isdigit() and len(stem) == 8 and stem > normalize_date(end_date):
            continue
        df = pl.read_parquet(path) if path.suffix == ".parquet" else pl.read_csv(path, infer_schema_length=2000)
        frames.append(df)
    raw = pl.concat(frames, how="diagonal_relaxed")
    cols = raw.columns
    required = ["date", "code", "open", "high", "low", "close", "amount"]
    missing = [k for k in required if config.FIELD_MAP.get(k) not in cols]
    if missing:
        raise ValueError(f"日 K 缺少必要字段映射：{missing}，当前字段：{cols}")
    exprs = [
        pl.col(config.FIELD_MAP["date"]).cast(pl.Utf8).map_elements(normalize_date, return_dtype=pl.Utf8).alias("date"),
        pl.col(config.FIELD_MAP["code"]).cast(pl.Utf8).map_elements(normalize_code, return_dtype=pl.Utf8).alias("code"),
        pl.col(config.FIELD_MAP["open"]).cast(pl.Float64, strict=False).alias("open"),
        pl.col(config.FIELD_MAP["high"]).cast(pl.Float64, strict=False).alias("high"),
        pl.col(config.FIELD_MAP["low"]).cast(pl.Float64, strict=False).alias("low"),
        pl.col(config.FIELD_MAP["close"]).cast(pl.Float64, strict=False).alias("close"),
        pl.col(config.FIELD_MAP["amount"]).cast(pl.Float64, strict=False).alias("amount_raw"),
    ]
    if config.FIELD_MAP.get("pre_close") in cols:
        exprs.append(pl.col(config.FIELD_MAP["pre_close"]).cast(pl.Float64, strict=False).alias("pre_close"))
    else:
        exprs.append(pl.lit(None, dtype=pl.Float64).alias("pre_close"))
    if config.FIELD_MAP.get("pctChg") in cols:
        exprs.append(pl.col(config.FIELD_MAP["pctChg"]).cast(pl.Float64, strict=False).alias("pctChg"))
    else:
        exprs.append(pl.lit(None, dtype=pl.Float64).alias("pctChg"))
    if config.FIELD_MAP.get("tradestatus") in cols:
        exprs.append(pl.col(config.FIELD_MAP["tradestatus"]).cast(pl.Utf8).alias("tradestatus"))
    else:
        exprs.append(pl.lit("1").alias("tradestatus"))
    if config.FIELD_MAP.get("isST") in cols:
        exprs.append(pl.col(config.FIELD_MAP["isST"]).cast(pl.Utf8).alias("isST"))
    else:
        exprs.append(pl.lit("0").alias("isST"))
    df = raw.select(exprs)
    df = df.with_columns(
        (pl.col("amount_raw") * (1000.0 if config.TUSHARE_AMOUNT_IS_THOUSAND_YUAN else 1.0)).alias("amount")
    ).drop("amount_raw")
    df = df.join(universe, on="code", how="inner", suffix="_universe")
    if "industry_l1_universe" in df.columns:
        df = df.with_columns(pl.col("industry_l1_universe").alias("industry_l1")).drop("industry_l1_universe")
    df = df.sort(["code", "date"])
    df = _add_hfq_prices(df, logger)
    if not config.KEEP_RAW_PRICE_COLUMNS:
        df = df.drop(["open_raw", "high_raw", "low_raw", "close_raw"])
    logger.info("读取日 K 行数：%s，股票数：%s，日期：%s 至 %s", df.height, df["code"].n_unique(), df["date"].min(), df["date"].max())
    return df
