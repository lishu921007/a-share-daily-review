from __future__ import annotations

from pathlib import Path
import pandas as pd
import polars as pl

import config


RET_COLS = ["ret_1d_open", "ret_2d_open", "ret_3d_open", "ret_5d_open", "ret_10d_open", "ret_20d_open", "ret_40d_open", "ret_60d_open"]


def _win_rate(s: pd.Series) -> float:
    s = s.dropna()
    return float((s > 0).mean()) if len(s) else float("nan")


def _summary(pdf: pd.DataFrame) -> pd.DataFrame:
    valid = pdf[pdf["valid_entry"] == True]
    row = {"total_signals": len(pdf), "valid_entries": len(valid), "invalid_entries": len(pdf) - len(valid)}
    for col in RET_COLS:
        label = col.replace("ret_", "avg_ret_").replace("_open", "")
        row[label] = valid[col].mean()
    for d in [5, 10, 20]:
        row[f"median_ret_{d}d"] = valid[f"ret_{d}d_open"].median()
        row[f"win_rate_{d}d"] = _win_rate(valid[f"ret_{d}d_open"])
    row["avg_trend_return"] = valid["trend_return"].mean()
    row["median_trend_return"] = valid["trend_return"].median()
    row["trend_win_rate"] = _win_rate(valid["trend_return"])
    row["avg_trend_hold_days"] = valid["trend_hold_days"].mean()
    return pd.DataFrame([row])


def _group(pdf: pd.DataFrame, group_col: str | list[str]) -> pd.DataFrame:
    rows = []
    valid = pdf[pdf["valid_entry"] == True].copy()
    group_cols = [group_col] if isinstance(group_col, str) else group_col
    if valid.empty or any(c not in valid.columns for c in group_cols):
        return pd.DataFrame()
    for key, g in valid.groupby(group_cols, dropna=False):
        key_tuple = key if isinstance(key, tuple) else (key,)
        row = {col: value for col, value in zip(group_cols, key_tuple)}
        mask = pd.Series([True] * len(pdf), index=pdf.index)
        for col, value in zip(group_cols, key_tuple):
            mask &= pdf[col].eq(value)
        row.update({"signals": int(mask.sum()), "valid_entries": len(g)})
        for d in [5, 10, 20, 40, 60]:
            row[f"avg_ret_{d}d"] = g[f"ret_{d}d_open"].mean()
            row[f"median_ret_{d}d"] = g[f"ret_{d}d_open"].median()
            row[f"win_rate_{d}d"] = _win_rate(g[f"ret_{d}d_open"])
        row["avg_trend_return"] = g["trend_return"].mean()
        row["median_trend_return"] = g["trend_return"].median()
        row["trend_win_rate"] = _win_rate(g["trend_return"])
        row["avg_trend_hold_days"] = g["trend_hold_days"].mean()
        row["max_trend_return"] = g["trend_return"].max()
        row["min_trend_return"] = g["trend_return"].min()
        rows.append(row)
    return pd.DataFrame(rows)


def _distribution(pdf: pd.DataFrame) -> pd.DataFrame:
    rows = []
    valid = pdf[pdf["valid_entry"] == True]
    metrics = ["ret_5d_open", "ret_10d_open", "ret_20d_open", "ret_40d_open", "ret_60d_open", "trend_return"]
    for signal_type, g in valid.groupby("signal_type", dropna=False):
        for metric in metrics:
            s = g[metric].dropna()
            for label, lo, hi in config.RETURN_BUCKETS:
                mask = pd.Series([True] * len(s), index=s.index)
                if lo is not None:
                    mask &= s > lo
                if hi is not None:
                    mask &= s <= hi
                rows.append({"signal_type": signal_type, "metric": metric, "bucket": label, "count": int(mask.sum()), "ratio": float(mask.mean()) if len(s) else None})
    return pd.DataFrame(rows)


def write_statistics(validation: pl.DataFrame, output_dir: Path, stamp: str, logger) -> dict[str, Path]:
    pdf = validation.to_pandas() if validation.height else pd.DataFrame()
    paths = {}
    if pdf.empty:
        for name in ["summary", "by_signal_type", "by_industry", "by_year", "return_distribution"]:
            path = output_dir / "stats" / f"{name}_{stamp}.csv"
            pd.DataFrame().to_csv(path, index=False)
            paths[name] = path
        return paths
    pdf["year"] = pdf["signal_date"].astype(str).str[:4]
    outputs = {
        "summary": _summary(pdf),
        "by_signal_type": _group(pdf, "signal_type"),
        "by_industry": _group(pdf, "industry_l1"),
        "by_year": _group(pdf, "year"),
        "by_weekly_filter_pass": _group(pdf, "weekly_filter_pass"),
        "by_signal_type_weekly": _group(pdf, ["signal_type", "weekly_filter_pass"]),
        "return_distribution": _distribution(pdf),
    }
    for name, df in outputs.items():
        path = output_dir / "stats" / f"{name}_{stamp}.csv"
        df.to_csv(path, index=False)
        paths[name] = path
    logger.info("统计文件输出完成：%s", {k: str(v) for k, v in paths.items()})
    return paths


def write_v1_v2_compare(v1_validation: pl.DataFrame, v2_validation: pl.DataFrame, output_dir: Path, stamp: str) -> Path:
    rows = []
    signal_types = list(config.PATTERN_QUALITY.keys())
    for version, validation in [("V1_daily_only", v1_validation), ("V2_weekly_loose", v2_validation)]:
        pdf = validation.to_pandas() if validation.height else pd.DataFrame()
        grouped = _group(pdf, "signal_type") if not pdf.empty else pd.DataFrame()
        grouped = grouped.set_index("signal_type").reindex(signal_types).reset_index()
        grouped["signals"] = grouped["signals"].fillna(0).astype(int)
        grouped["valid_entries"] = grouped["valid_entries"].fillna(0).astype(int)
        grouped.insert(0, "version", version)
        rows.append(grouped)
    out = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    path = output_dir / "stats" / f"v1_v2_compare_{stamp}.csv"
    out.to_csv(path, index=False)
    return path
