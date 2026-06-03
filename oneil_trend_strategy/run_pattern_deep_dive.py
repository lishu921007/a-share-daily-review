#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
import polars as pl

import config
from src.data_loader import load_daily_data, load_universe
from src.feature_engineering import add_daily_features
from src.industry_features import add_industry_features
from src.validation_engine import validate_signals
from src.utils import setup_logger


TARGET_PATTERNS = ["base_on_base", "cup_with_handle"]


@dataclass(frozen=True)
class ExitScenario:
    name: str
    enable_failed_breakout: bool
    break_ma20_after_days: int


SCENARIOS = [
    ExitScenario("A_default_fast_exit", True, 0),
    ExitScenario("B_no_failed_breakout", False, 0),
    ExitScenario("C_no_failed_breakout_ma20_after_5d", False, 5),
    ExitScenario("D_trend_hold_ma20_after_10d", False, 10),
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="base_on_base / cup_with_handle 卖点敏感性深挖")
    p.add_argument("--daily_dir", type=Path, default=config.DAILY_DATA_DIR)
    p.add_argument("--universe_dir", type=Path, default=config.UNIVERSE_DIR)
    p.add_argument("--signals_path", type=Path, default=None, help="默认自动读取最新 V2 weekly loose signals")
    p.add_argument("--start_date", default=config.START_DATE)
    p.add_argument("--end_date", default="2026-06-01")
    p.add_argument("--output_dir", type=Path, default=config.OUTPUT_DIR)
    return p.parse_args()


def latest_v2_signals(output_dir: Path) -> Path:
    files = sorted((output_dir / "signals").glob("signals_*_v2_weekly_loose.csv"))
    if not files:
        raise FileNotFoundError(f"未找到 V2 signals 文件：{output_dir / 'signals'}")
    return files[-1]


def win_rate(s: pd.Series) -> float:
    s = s.dropna()
    return float((s > 0).mean()) if len(s) else float("nan")


def summarize(validation: pl.DataFrame, scenario: ExitScenario) -> pd.DataFrame:
    pdf = validation.to_pandas()
    valid = pdf[pdf["valid_entry"] == True].copy()
    rows = []
    for signal_type, g in valid.groupby("signal_type", dropna=False):
        row = {
            "scenario": scenario.name,
            "failed_breakout_exit": scenario.enable_failed_breakout,
            "break_ma20_after_days": scenario.break_ma20_after_days,
            "signal_type": signal_type,
            "valid_entries": len(g),
            "avg_trend_return": g["trend_return"].mean(),
            "median_trend_return": g["trend_return"].median(),
            "trend_win_rate": win_rate(g["trend_return"]),
            "avg_trend_hold_days": g["trend_hold_days"].mean(),
            "median_trend_hold_days": g["trend_hold_days"].median(),
            "avg_trend_max_return_during_hold": g["trend_max_return_during_hold"].mean(),
            "avg_trend_min_return_during_hold": g["trend_min_return_during_hold"].mean(),
            "avg_trend_max_drawdown_during_hold": g["trend_max_drawdown_during_hold"].mean(),
        }
        for d in [20, 40, 60]:
            col = f"ret_{d}d_open"
            row[f"avg_ret_{d}d"] = g[col].mean()
            row[f"median_ret_{d}d"] = g[col].median()
            row[f"win_rate_{d}d"] = win_rate(g[col])
        rows.append(row)
    return pd.DataFrame(rows)


def exit_reason_summary(validation: pl.DataFrame, scenario: ExitScenario) -> pd.DataFrame:
    pdf = validation.to_pandas()
    valid = pdf[pdf["valid_entry"] == True].copy()
    if valid.empty:
        return pd.DataFrame()
    grouped = (
        valid.groupby(["signal_type", "trend_exit_reason"], dropna=False)
        .size()
        .reset_index(name="count")
    )
    totals = grouped.groupby("signal_type")["count"].transform("sum")
    grouped.insert(0, "scenario", scenario.name)
    grouped["ratio"] = grouped["count"] / totals
    return grouped


def quantile_summary(validation: pl.DataFrame, scenario: ExitScenario) -> pd.DataFrame:
    pdf = validation.to_pandas()
    valid = pdf[pdf["valid_entry"] == True].copy()
    rows = []
    for signal_type, g in valid.groupby("signal_type", dropna=False):
        s = g["trend_return"].dropna()
        if s.empty:
            continue
        rows.append(
            {
                "scenario": scenario.name,
                "signal_type": signal_type,
                "p10_trend_return": s.quantile(0.10),
                "p25_trend_return": s.quantile(0.25),
                "p50_trend_return": s.quantile(0.50),
                "p75_trend_return": s.quantile(0.75),
                "p90_trend_return": s.quantile(0.90),
                "right_tail_20pct_ratio": float((s >= 0.20).mean()),
                "left_tail_minus10pct_ratio": float((s <= -0.10).mean()),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir if args.output_dir.is_absolute() else (Path.cwd() / args.output_dir).resolve()
    deep_dir = output_dir / "deep_dive"
    deep_dir.mkdir(parents=True, exist_ok=True)
    logger = setup_logger(output_dir / "logs")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    signals_path = args.signals_path or latest_v2_signals(output_dir)
    logger.info("读取 V2 signals：%s", signals_path)
    signals = pl.read_csv(signals_path, try_parse_dates=False)
    signals = signals.with_columns(
        pl.col("date").cast(pl.Utf8).str.replace_all("-", "").alias("date"),
        pl.col("code").cast(pl.Utf8).alias("code"),
    )
    signals = signals.filter(pl.col("signal_type").is_in(TARGET_PATTERNS))
    logger.info("深挖目标信号：%s 条，形态=%s", signals.height, TARGET_PATTERNS)

    universe = load_universe(args.universe_dir, logger)
    daily = load_daily_data(args.daily_dir, universe, args.start_date, args.end_date, logger)
    features = add_daily_features(daily, logger)
    features, _ = add_industry_features(features, logger)

    original_failed_breakout = config.ENABLE_FAILED_BREAKOUT_EXIT
    original_ma20_after_days = config.ENABLE_BREAK_MA20_EXIT_AFTER_DAYS

    all_summary = []
    all_reasons = []
    all_quantiles = []
    try:
        for scenario in SCENARIOS:
            config.ENABLE_FAILED_BREAKOUT_EXIT = scenario.enable_failed_breakout
            config.ENABLE_BREAK_MA20_EXIT_AFTER_DAYS = scenario.break_ma20_after_days
            logger.info("开始卖点情景：%s", scenario)
            validation = validate_signals(signals, features, logger)
            validation_path = deep_dir / f"validation_{scenario.name}_{stamp}.csv"
            validation.write_csv(validation_path)
            logger.info("情景验证明细输出：%s", validation_path)
            all_summary.append(summarize(validation, scenario))
            all_reasons.append(exit_reason_summary(validation, scenario))
            all_quantiles.append(quantile_summary(validation, scenario))
    finally:
        config.ENABLE_FAILED_BREAKOUT_EXIT = original_failed_breakout
        config.ENABLE_BREAK_MA20_EXIT_AFTER_DAYS = original_ma20_after_days

    summary = pd.concat(all_summary, ignore_index=True)
    reasons = pd.concat(all_reasons, ignore_index=True)
    quantiles = pd.concat(all_quantiles, ignore_index=True)

    summary_path = deep_dir / f"exit_sensitivity_summary_{stamp}.csv"
    reasons_path = deep_dir / f"exit_reason_summary_{stamp}.csv"
    quantiles_path = deep_dir / f"trend_return_quantiles_{stamp}.csv"
    summary.to_csv(summary_path, index=False)
    reasons.to_csv(reasons_path, index=False)
    quantiles.to_csv(quantiles_path, index=False)

    logger.info("深挖汇总输出：%s", summary_path)
    logger.info("卖出原因输出：%s", reasons_path)
    logger.info("分位数输出：%s", quantiles_path)


if __name__ == "__main__":
    main()
