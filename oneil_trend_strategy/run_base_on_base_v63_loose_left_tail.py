#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

import pandas as pd
import polars as pl

import config
from src.data_loader import load_daily_data, load_universe
from src.feature_engineering import add_daily_features
from src.industry_features import add_industry_features
from src.utils import setup_logger


@dataclass(frozen=True)
class LooseScenario:
    scenario_id: str
    name: str
    loose_ret80_max: float
    loose_entry_gap_max: float
    loose_entry_over_pivot_max: float
    allowed_loose_reasons: tuple[str, ...]

    @property
    def label(self) -> str:
        return (
            f"{self.scenario_id}_ret80{self.loose_ret80_max:.2f}_"
            f"gap{self.loose_entry_gap_max:.2f}_over{self.loose_entry_over_pivot_max:.2f}_"
            f"{'-'.join(self.allowed_loose_reasons)}"
        ).replace(".", "p")


@dataclass(frozen=True)
class BuyFilter:
    rs60_min: float
    amount_ratio_min: float
    week_close_to_high_30_min: float
    base2_depth_max: float
    breakout_pct_max: float
    ret80_max: float
    base2_days_min: int
    base2_days_max: int
    base2_volume_contract_max: float
    prior_leg_return_max: float

    @property
    def name(self) -> str:
        return (
            f"rs{self.rs60_min:.1f}_amt{self.amount_ratio_min:.1f}_"
            f"wpos{self.week_close_to_high_30_min:.2f}_depth{self.base2_depth_max:.2f}_"
            f"bpct{self.breakout_pct_max:.2f}_ret80{self.ret80_max:.1f}_"
            f"b2d{self.base2_days_min}-{self.base2_days_max}_"
            f"vcon{self.base2_volume_contract_max:.1f}_leg{self.prior_leg_return_max:.1f}"
        ).replace(".", "p")


@dataclass(frozen=True)
class ExitRule:
    hard_stop: float
    fail_window_days: int
    fail_pivot_buffer: float
    ma20_after_days: int
    ma20_confirm_days: int
    trailing_stop: float
    max_hold_days: int

    @property
    def name(self) -> str:
        return (
            f"hs{self.hard_stop:.2f}_fw{self.fail_window_days}_pv{self.fail_pivot_buffer:.2f}_"
            f"ma{self.ma20_after_days}x{self.ma20_confirm_days}_tr{self.trailing_stop:.2f}_mh{self.max_hold_days}"
        ).replace(".", "p")


BUY_FILTERS = [
    # V6.2 最佳组合，V6.3 只测试 loose 左尾约束，不再扩大买点网格。
    BuyFilter(0.60, 1.00, 0.80, 0.15, 0.12, 0.80, 8, 60, 1.10, 0.60),
]

EXIT_RULES = [
    # V6.2 最佳卖点组合。
    ExitRule(hard_stop=0.08, fail_window_days=3, fail_pivot_buffer=0.97, ma20_after_days=20, ma20_confirm_days=2, trailing_stop=0.12, max_hold_days=60),
]

LOOSE_SCENARIOS = [
    LooseScenario("A", "V6.2 原始 loose", 0.80, 0.08, 0.15, ("leg1_high_too_late", "missing_breakout1")),
    LooseScenario("B", "ret_80 <= 0.30", 0.30, 0.08, 0.15, ("leg1_high_too_late", "missing_breakout1")),
    LooseScenario("C", "ret_80 <= 0.30 + 只保留 leg1_high_too_late", 0.30, 0.08, 0.15, ("leg1_high_too_late",)),
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="base_on_base V6.3 loose 左尾约束实验")
    p.add_argument("--daily_dir", type=Path, default=config.DAILY_DATA_DIR)
    p.add_argument("--universe_dir", type=Path, default=config.UNIVERSE_DIR)
    p.add_argument("--signals_path", type=Path, default=None, help="默认自动读取最新 V2 weekly loose signals")
    p.add_argument("--start_date", default=config.START_DATE)
    p.add_argument("--end_date", default="2026-06-01")
    p.add_argument("--output_dir", type=Path, default=config.OUTPUT_DIR)
    p.add_argument("--min_samples", type=int, default=200)
    return p.parse_args()


def latest_v2_signals(output_dir: Path) -> Path:
    files = sorted((output_dir / "signals").glob("signals_*_v2_weekly_loose.csv"))
    if not files:
        raise FileNotFoundError(f"未找到 V2 signals 文件：{output_dir / 'signals'}")
    return files[-1]


def max_drawdown(closes: list[float]) -> float | None:
    if not closes:
        return None
    peak = closes[0]
    mdd = 0.0
    for close in closes:
        if pd.isna(close):
            continue
        peak = max(peak, close)
        if peak > 0:
            mdd = min(mdd, close / peak - 1)
    return mdd


def win_rate(s: pd.Series) -> float:
    s = s.dropna()
    return float((s > 0).mean()) if len(s) else float("nan")


def load_base_signals(signals_path: Path, feature_df: pl.DataFrame) -> pd.DataFrame:
    signals = pl.read_csv(signals_path, try_parse_dates=False).with_columns(
        pl.col("date").cast(pl.Utf8).str.replace_all("-", "").alias("date"),
        pl.col("code").cast(pl.Utf8).alias("code"),
    )
    signals = signals.filter(pl.col("signal_type") == "base_on_base")
    feature_cols = [
        "date", "code", "low_30_shift1", "high_30_shift1", "ret_80", "pctChg",
        "ma20", "ma60", "close_to_high_120", "rs_120_rank_pct",
        "open_raw", "high_raw", "low_raw", "close_raw", "hfq_factor", "suspect_ex_dividend",
    ]
    enriched = signals.join(feature_df.select(feature_cols), on=["date", "code"], how="left")
    enriched = enriched.with_columns(
        (pl.col("pivot_price") / pl.col("low_30_shift1") - 1).alias("base2_depth"),
        (pl.col("close") / pl.col("pivot_price") - 1).alias("breakout_close_over_pivot"),
    )
    return enriched.to_pandas()


def tag_v62_structure(signals: pd.DataFrame) -> pd.DataFrame:
    signals = signals.copy()
    strict = signals["structure_valid"] == True
    loose = (
        (~strict)
        & (signals["structure_invalid_reason"].isin(["leg1_high_too_late", "missing_breakout1"]))
        & (signals["rs_60_rank_pct"] >= 0.65)
        & (signals["amount_ratio_20"] >= 1.50)
        & (signals["week_close_to_high_30"] >= 0.85)
        & (signals["pctChg"] <= 0.105)
        & (signals["ret_80"] <= 0.80)
        & (signals["base2_depth"] <= 0.20)
    )
    signals["v62_label"] = "reject"
    signals.loc[strict, "v62_label"] = "strict"
    signals.loc[loose, "v62_label"] = "loose"
    return signals


def filter_for_scenario(validation: pd.DataFrame, scenario: LooseScenario) -> pd.DataFrame:
    valid = validation[validation["valid_entry"] == True].copy()
    strict = valid["v62_label"] == "strict"
    loose = (
        (valid["v62_label"] == "loose")
        & (valid["structure_invalid_reason"].isin(scenario.allowed_loose_reasons))
        & (valid["ret_80"] <= scenario.loose_ret80_max)
        & (valid["entry_gap_from_signal_close"].fillna(99) <= scenario.loose_entry_gap_max)
        & (valid["entry_over_pivot_hfq"].fillna(99) <= scenario.loose_entry_over_pivot_max)
    )
    out = valid[strict | loose].copy()
    out["v63_scenario_id"] = scenario.scenario_id
    out["v63_scenario_name"] = scenario.name
    return out


def return_stats(rows: pd.DataFrame) -> dict:
    s = rows["trend_return"].dropna() if not rows.empty else pd.Series(dtype=float)
    return {
        "entries": len(rows),
        "avg_trend_return": s.mean() if len(s) else float("nan"),
        "median_trend_return": s.median() if len(s) else float("nan"),
        "trend_win_rate": win_rate(s),
        "right_tail_20pct_ratio": float((s >= 0.20).mean()) if len(s) else float("nan"),
        "left_tail_minus10pct_ratio": float((s <= -0.10).mean()) if len(s) else float("nan"),
        "avg_max_drawdown_during_hold": rows["max_drawdown_during_hold"].mean() if "max_drawdown_during_hold" in rows else float("nan"),
        "avg_hold_days": rows["hold_days"].mean() if "hold_days" in rows else float("nan"),
    }


def apply_buy_filter(signals: pd.DataFrame, buy_filter: BuyFilter) -> pd.DataFrame:
    mask = (
        (signals["rs_60_rank_pct"] >= buy_filter.rs60_min)
        & (signals["amount_ratio_20"] >= buy_filter.amount_ratio_min)
        & (signals["week_close_to_high_30"] >= buy_filter.week_close_to_high_30_min)
        & (signals["base2_depth"] <= buy_filter.base2_depth_max)
        & (signals["pctChg"] <= buy_filter.breakout_pct_max)
        & (signals["ret_80"] <= buy_filter.ret80_max)
        & (signals["v62_label"].isin(["strict", "loose"]))
        & (
            (signals["v62_label"] == "loose")
            | (
                (signals["base2_days"] >= buy_filter.base2_days_min)
                & (signals["base2_days"] <= buy_filter.base2_days_max)
                & (signals["base2_volume_contract"] <= buy_filter.base2_volume_contract_max)
                & (signals["prior_leg_return"] <= buy_filter.prior_leg_return_max)
            )
        )
    )
    return signals[mask].copy()


def build_price_maps(feature_df: pl.DataFrame) -> dict[str, pd.DataFrame]:
    cols = [
        "date", "code", "open", "high", "low", "close", "ma20", "tradestatus",
        "amount", "pctChg",
        "open_raw", "high_raw", "low_raw", "close_raw", "hfq_factor", "suspect_ex_dividend",
    ]
    pdf = feature_df.select(cols).to_pandas()
    pdf = pdf.sort_values(["code", "date"])
    return {code: g.reset_index(drop=True) for code, g in pdf.groupby("code", sort=False)}


def infer_structure(signal, prices: pd.DataFrame) -> dict:
    idx_list = prices.index[prices["date"] == signal.date].tolist()
    empty = {
        "structure_valid": False,
        "structure_invalid_reason": "missing_signal_date",
        "base1_start": None,
        "base1_end": None,
        "breakout1_date": None,
        "breakout1_price_hfq": None,
        "breakout1_pct": None,
        "leg1_high_date": None,
        "leg1_high_price_hfq": None,
        "prior_leg_return": None,
        "leg1_days": None,
        "base2_start": None,
        "base2_end": None,
        "base2_days": None,
        "base2_high_hfq": None,
        "base2_low_hfq": None,
        "base2_depth_struct": None,
        "base2_volume_contract": None,
        "base2_range_contract": None,
        "breakout2_date": signal.date,
        "breakout2_pct": getattr(signal, "pctChg", None),
    }
    if not idx_list:
        return empty
    sig_idx = idx_list[0]
    if sig_idx < 90:
        empty["structure_invalid_reason"] = "not_enough_lookback"
        return empty

    prior = prices.iloc[max(0, sig_idx - 120):sig_idx].copy()
    prior = prior.reset_index(drop=True)
    if len(prior) < 90:
        empty["structure_invalid_reason"] = "not_enough_prior_window"
        return empty

    prior["rolling_high20_shift1"] = prior["high"].rolling(20, min_periods=20).max().shift(1)
    breakout_candidates = prior[
        (prior["close"] > prior["rolling_high20_shift1"])
        & (prior["pctChg"].fillna(0) >= 0.02)
    ].copy()
    # 第一次突破不能离第二次突破太近，否则容易把第二平台内部波动误识别成第一次突破。
    breakout_candidates = breakout_candidates[breakout_candidates.index <= len(prior) - 25]
    if breakout_candidates.empty:
        empty["structure_invalid_reason"] = "missing_breakout1"
        return empty

    b1_pos = int(breakout_candidates.index[-1])
    breakout1 = prior.iloc[b1_pos]
    after_b1 = prior.iloc[b1_pos:min(len(prior), b1_pos + 60)]
    if after_b1.empty:
        empty["structure_invalid_reason"] = "missing_leg1"
        return empty
    leg1_rel = int(after_b1["high"].idxmax())
    leg1_high = prior.iloc[leg1_rel]
    if leg1_rel >= len(prior) - 3:
        empty["structure_invalid_reason"] = "leg1_high_too_late"
        return empty

    base2 = prior.iloc[leg1_rel + 1:].copy()
    if len(base2) < 3:
        empty["structure_invalid_reason"] = "base2_too_short"
        return empty
    leg1 = prior.iloc[b1_pos:leg1_rel + 1].copy()
    base1 = prior.iloc[max(0, b1_pos - 30):b1_pos].copy()

    base2_first = base2.iloc[: max(1, len(base2) // 2)]
    base2_second = base2.iloc[max(1, len(base2) // 2):]
    base2_high = float(base2["high"].max())
    base2_low = float(base2["low"].min())
    leg1_amount = float(leg1["amount"].mean()) if len(leg1) else float("nan")
    base2_amount = float(base2["amount"].mean()) if len(base2) else float("nan")
    volume_contract = base2_amount / leg1_amount if leg1_amount and pd.notna(leg1_amount) else None
    first_range = (base2_first["high"] / base2_first["low"] - 1).mean()
    second_range = (base2_second["high"] / base2_second["low"] - 1).mean() if len(base2_second) else None
    range_contract = second_range / first_range if first_range and pd.notna(first_range) else None
    prior_leg_return = float(leg1_high["high"]) / float(breakout1["close"]) - 1

    return {
        "structure_valid": True,
        "structure_invalid_reason": "",
        "base1_start": base1.iloc[0]["date"] if len(base1) else None,
        "base1_end": prior.iloc[b1_pos - 1]["date"] if b1_pos > 0 else None,
        "breakout1_date": breakout1["date"],
        "breakout1_price_hfq": float(breakout1["close"]),
        "breakout1_pct": float(breakout1["pctChg"]) if pd.notna(breakout1["pctChg"]) else None,
        "leg1_high_date": leg1_high["date"],
        "leg1_high_price_hfq": float(leg1_high["high"]),
        "prior_leg_return": prior_leg_return,
        "leg1_days": leg1_rel - b1_pos + 1,
        "base2_start": base2.iloc[0]["date"],
        "base2_end": base2.iloc[-1]["date"],
        "base2_days": len(base2),
        "base2_high_hfq": base2_high,
        "base2_low_hfq": base2_low,
        "base2_depth_struct": base2_high / base2_low - 1 if base2_low > 0 else None,
        "base2_volume_contract": volume_contract,
        "base2_range_contract": range_contract,
        "breakout2_date": signal.date,
        "breakout2_pct": getattr(signal, "pctChg", None),
    }


def add_structure_features(signals: pd.DataFrame, price_maps: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for signal in signals.itertuples(index=False):
        prices = price_maps.get(signal.code)
        if prices is None:
            rows.append({"structure_valid": False, "structure_invalid_reason": "missing_price_data"})
        else:
            rows.append(infer_structure(signal, prices))
    struct = pd.DataFrame(rows)
    return pd.concat([signals.reset_index(drop=True), struct.reset_index(drop=True)], axis=1)


def evaluate_one_signal(signal, prices: pd.DataFrame, exit_rule: ExitRule) -> dict:
    idx_list = prices.index[prices["date"] == signal.date].tolist()
    base = {
        "signal_date": signal.date,
        "entry_date": None,
        "code": signal.code,
        "industry_l1": signal.industry_l1,
        "signal_price_mode": "hfq",
        "trade_price_mode": "raw",
        "return_mode": "raw_price_with_hfq_factor",
        "pivot_price_hfq": signal.pivot_price,
        "signal_close_hfq": signal.close,
        "signal_close_raw": getattr(signal, "close_raw", None),
        "signal_hfq_factor": getattr(signal, "hfq_factor", None),
        "entry_price": None,
        "entry_price_raw": None,
        "entry_price_hfq": None,
        "valid_entry": False,
        "invalid_reason": "",
    }
    if not idx_list or idx_list[0] + 1 >= len(prices):
        base["invalid_reason"] = "no_next_trade_day"
        return base
    sig_idx = idx_list[0]
    entry = prices.iloc[sig_idx + 1]
    base["entry_date"] = entry["date"]
    if pd.isna(entry["open"]) or str(entry["tradestatus"]) != "1":
        base["invalid_reason"] = "invalid_entry"
        return base

    entry_price_hfq = float(entry["open"])
    entry_price_raw = float(entry["open_raw"])
    entry_factor = float(entry["hfq_factor"])
    pivot = float(signal.pivot_price)
    future = prices.iloc[sig_idx + 1:].reset_index(drop=True)
    base.update(
        {
            "entry_price": entry_price_raw,
            "entry_price_raw": entry_price_raw,
            "entry_price_hfq": entry_price_hfq,
            "entry_hfq_factor": entry_factor,
            "entry_gap_from_signal_close": entry_price_hfq / float(signal.close) - 1,
            "entry_gap_from_signal_close_raw": (
                entry_price_raw / float(signal.close_raw) - 1
                if pd.notna(getattr(signal, "close_raw", None)) and float(signal.close_raw) > 0
                else None
            ),
            "entry_over_pivot_hfq": entry_price_hfq / pivot - 1,
            "valid_entry": True,
        }
    )

    highest_close = -float("inf")
    closes: list[float] = []
    below_ma20_streak = 0
    for hold_idx, row in enumerate(future.itertuples(index=False), start=0):
        close = float(row.close)
        low = float(row.low)
        ma20 = getattr(row, "ma20")
        closes.append(close)
        highest_close = max(highest_close, close)
        if pd.notna(ma20) and close < float(ma20):
            below_ma20_streak += 1
        else:
            below_ma20_streak = 0

        reason = None
        if close <= entry_price_hfq * (1 - exit_rule.hard_stop):
            reason = "hard_stop"
        elif hold_idx < exit_rule.fail_window_days and close < pivot * exit_rule.fail_pivot_buffer:
            reason = "pivot_failed"
        elif hold_idx < exit_rule.fail_window_days and low < pivot * 0.95 and close < pivot:
            reason = "base_failed"
        elif highest_close > 0 and close < highest_close * (1 - exit_rule.trailing_stop):
            reason = "trailing_stop"
        elif hold_idx >= exit_rule.ma20_after_days and below_ma20_streak >= exit_rule.ma20_confirm_days:
            reason = "break_ma20_confirmed"
        elif hold_idx >= exit_rule.max_hold_days:
            reason = "timeout_exit"
        if not reason:
            continue

        exit_idx = hold_idx + 1
        if exit_idx < len(future):
            exit_row = future.iloc[exit_idx]
            exit_date = exit_row["date"]
            exit_price_hfq = float(exit_row["open"])
            exit_price_raw = float(exit_row["open_raw"])
            exit_factor = float(exit_row["hfq_factor"])
        else:
            exit_date = row.date
            exit_price_hfq = close
            exit_price_raw = float(row.close_raw)
            exit_factor = float(row.hfq_factor)
            reason = "data_end_exit"
        returns = [c / entry_price_hfq - 1 for c in closes]
        raw_price_return = exit_price_raw / entry_price_raw - 1
        trend_return = exit_price_raw / entry_price_raw * exit_factor / entry_factor - 1
        hold_slice = future.iloc[: hold_idx + 1]
        base.update(
            {
                "exit_signal_date": row.date,
                "exit_date": exit_date,
                "exit_price": exit_price_raw,
                "exit_price_raw": exit_price_raw,
                "exit_price_hfq": exit_price_hfq,
                "exit_hfq_factor": exit_factor,
                "hold_days": hold_idx + 1,
                "raw_price_return": raw_price_return,
                "trend_return": trend_return,
                "trade_return_adj": trend_return,
                "exit_reason": reason,
                "max_return_during_hold": max(returns) if returns else None,
                "min_return_during_hold": min(returns) if returns else None,
                "max_drawdown_during_hold": max_drawdown(closes),
                "has_ex_dividend_during_holding": bool(hold_slice["suspect_ex_dividend"].fillna(False).any()),
            }
        )
        return base

    if len(future) == 0:
        base["invalid_reason"] = "no_future_data"
        return base
    row = future.iloc[-1]
    exit_price_hfq = float(row["close"])
    exit_price_raw = float(row["close_raw"])
    exit_factor = float(row["hfq_factor"])
    returns = [c / entry_price_hfq - 1 for c in closes]
    trend_return = exit_price_raw / entry_price_raw * exit_factor / entry_factor - 1
    base.update(
        {
            "exit_signal_date": row["date"],
            "exit_date": row["date"],
            "exit_price": exit_price_raw,
            "exit_price_raw": exit_price_raw,
            "exit_price_hfq": exit_price_hfq,
            "exit_hfq_factor": exit_factor,
            "hold_days": len(future),
            "raw_price_return": exit_price_raw / entry_price_raw - 1,
            "trend_return": trend_return,
            "trade_return_adj": trend_return,
            "exit_reason": "data_end_exit",
            "max_return_during_hold": max(returns) if returns else None,
            "min_return_during_hold": min(returns) if returns else None,
            "max_drawdown_during_hold": max_drawdown(closes),
            "has_ex_dividend_during_holding": bool(future["suspect_ex_dividend"].fillna(False).any()),
        }
    )
    return base


def evaluate(signals: pd.DataFrame, price_maps: dict[str, pd.DataFrame], exit_rule: ExitRule) -> pd.DataFrame:
    rows = []
    for signal in signals.itertuples(index=False):
        prices = price_maps.get(signal.code)
        if prices is None:
            rows.append({"signal_date": signal.date, "code": signal.code, "valid_entry": False, "invalid_reason": "missing_price_data"})
            continue
        row = evaluate_one_signal(signal, prices, exit_rule)
        for col in [
            "rs_60_rank_pct", "amount_ratio_20", "week_close_to_high_30", "week_close_to_high_52",
            "base2_depth", "breakout_close_over_pivot", "ret_80", "pctChg",
            "structure_valid", "structure_invalid_reason",
            "v62_label",
            "base1_start", "base1_end", "breakout1_date", "breakout1_price_hfq", "breakout1_pct",
            "leg1_high_date", "leg1_high_price_hfq", "prior_leg_return", "leg1_days",
            "base2_start", "base2_end", "base2_days", "base2_high_hfq", "base2_low_hfq",
            "base2_depth_struct", "base2_volume_contract", "base2_range_contract",
            "breakout2_date", "breakout2_pct",
        ]:
            row[col] = getattr(signal, col, None)
        rows.append(row)
    return pd.DataFrame(rows)


def summarize(validation: pd.DataFrame, buy_filter: BuyFilter, exit_rule: ExitRule, scenario: LooseScenario, min_samples: int) -> dict:
    valid = filter_for_scenario(validation, scenario)
    s = valid["trend_return"].dropna() if not valid.empty else pd.Series(dtype=float)
    left_tail = float((s <= -0.10).mean()) if len(s) else float("nan")
    right_tail = float((s >= 0.20).mean()) if len(s) else float("nan")
    avg_dd = valid["max_drawdown_during_hold"].mean() if "max_drawdown_during_hold" in valid else float("nan")
    median_ret = s.median() if len(s) else float("nan")
    avg_ret = s.mean() if len(s) else float("nan")
    wr = win_rate(s)
    score = (
        median_ret * 100
        + avg_ret * 30
        + wr * 2
        + right_tail * 3
        - left_tail * 4
        + (avg_dd if pd.notna(avg_dd) else 0) * 5
    )
    qualified_sample = len(valid) >= min_samples
    if not qualified_sample:
        score = score - 1000
    row = {
        "scenario_id": scenario.scenario_id,
        "scenario_name": scenario.name,
        "loose_ret80_max": scenario.loose_ret80_max,
        "loose_entry_gap_max": scenario.loose_entry_gap_max,
        "loose_entry_over_pivot_max": scenario.loose_entry_over_pivot_max,
        "allowed_loose_reasons": "|".join(scenario.allowed_loose_reasons),
        "buy_filter": buy_filter.name,
        "exit_rule": exit_rule.name,
        "score": score,
        "qualified_sample": qualified_sample,
        "signals": len(validation),
        "valid_entries": len(valid),
        "avg_trend_return": avg_ret,
        "median_trend_return": median_ret,
        "trend_win_rate": wr,
        "avg_hold_days": valid["hold_days"].mean() if "hold_days" in valid else float("nan"),
        "median_hold_days": valid["hold_days"].median() if "hold_days" in valid else float("nan"),
        "right_tail_20pct_ratio": right_tail,
        "left_tail_minus10pct_ratio": left_tail,
        "strict_entries": int((valid["v62_label"] == "strict").sum()) if "v62_label" in valid else 0,
        "loose_entries": int((valid["v62_label"] == "loose").sum()) if "v62_label" in valid else 0,
        "loose_entry_ratio": float((valid["v62_label"] == "loose").mean()) if "v62_label" in valid and len(valid) else float("nan"),
        "avg_max_return_during_hold": valid["max_return_during_hold"].mean() if "max_return_during_hold" in valid else float("nan"),
        "avg_max_drawdown_during_hold": avg_dd,
        "p25_trend_return": s.quantile(0.25) if len(s) else float("nan"),
        "p75_trend_return": s.quantile(0.75) if len(s) else float("nan"),
        **{f"buy_{k}": v for k, v in asdict(buy_filter).items()},
        **{f"exit_{k}": v for k, v in asdict(exit_rule).items()},
    }
    return row


def by_year(validation: pd.DataFrame, label: str, scenario: LooseScenario) -> pd.DataFrame:
    valid = filter_for_scenario(validation, scenario)
    if valid.empty:
        return pd.DataFrame()
    valid["year"] = valid["signal_date"].astype(str).str[:4]
    rows = []
    for year, g in valid.groupby("year"):
        s = g["trend_return"].dropna()
        rows.append(
            {
                "combo": label,
                "scenario_id": scenario.scenario_id,
                "scenario_name": scenario.name,
                "year": year,
                "valid_entries": len(g),
                "avg_trend_return": s.mean(),
                "median_trend_return": s.median(),
                "trend_win_rate": win_rate(s),
                "left_tail_minus10pct_ratio": float((s <= -0.10).mean()) if len(s) else None,
                "right_tail_20pct_ratio": float((s >= 0.20).mean()) if len(s) else None,
            }
        )
    return pd.DataFrame(rows)


def by_label_reason(validation: pd.DataFrame, label: str, scenario: LooseScenario) -> pd.DataFrame:
    valid = filter_for_scenario(validation, scenario)
    rows = []
    group_cols = ["v62_label", "structure_invalid_reason"]
    for (v62_label, reason), g in valid.groupby(group_cols, dropna=False):
        row = {
            "combo": label,
            "scenario_id": scenario.scenario_id,
            "scenario_name": scenario.name,
            "v62_label": v62_label,
            "structure_invalid_reason": reason,
        }
        row.update(return_stats(g))
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir if args.output_dir.is_absolute() else (Path.cwd() / args.output_dir).resolve()
    lab_dir = output_dir / "base_on_base_lab"
    lab_dir.mkdir(parents=True, exist_ok=True)
    logger = setup_logger(output_dir / "logs")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    signals_path = args.signals_path or latest_v2_signals(output_dir)
    logger.info("读取 V2 signals：%s", signals_path)

    universe = load_universe(args.universe_dir, logger)
    daily = load_daily_data(args.daily_dir, universe, args.start_date, args.end_date, logger)
    features = add_daily_features(daily, logger)
    features, _ = add_industry_features(features, logger)
    signals = load_base_signals(signals_path, features)
    logger.info("base_on_base V2 原始信号：%s", len(signals))
    price_maps = build_price_maps(features)
    signals = add_structure_features(signals, price_maps)
    signals = tag_v62_structure(signals)
    logger.info(
        "V6 结构识别有效信号：%s / %s",
        int(signals["structure_valid"].fillna(False).sum()),
        len(signals),
    )
    logger.info(
        "V6.2 标签分布：%s",
        signals["v62_label"].value_counts(dropna=False).to_dict(),
    )

    summary_rows = []
    validation_cache: dict[tuple[str, str], pd.DataFrame] = {}
    for buy_filter in BUY_FILTERS:
        filtered = apply_buy_filter(signals, buy_filter)
        if len(filtered) == 0:
            continue
        for exit_rule in EXIT_RULES:
            validation = evaluate(filtered, price_maps, exit_rule)
            key = (buy_filter.name, exit_rule.name)
            validation_cache[key] = validation
            for scenario in LOOSE_SCENARIOS:
                summary_rows.append(summarize(validation, buy_filter, exit_rule, scenario, args.min_samples))

    if not summary_rows:
        raise RuntimeError("没有任何 base_on_base 参数组合产生样本，请检查输入信号和过滤条件。")
    summary = pd.DataFrame(summary_rows).sort_values(["qualified_sample", "score", "valid_entries"], ascending=[False, False, False])
    summary_path = lab_dir / f"base_on_base_v63_loose_left_tail_summary_{stamp}.csv"
    summary.to_csv(summary_path, index=False)

    year_parts = []
    reason_parts = []
    label_reason_parts = []
    detail_paths = []
    for _, row in summary.iterrows():
        key = (row["buy_filter"], row["exit_rule"])
        validation = validation_cache[key]
        scenario = next(s for s in LOOSE_SCENARIOS if s.scenario_id == row["scenario_id"])
        validation = filter_for_scenario(validation, scenario)
        label = f"{row['scenario_id']}__{row['buy_filter']}__{row['exit_rule']}"
        year_parts.append(by_year(validation, label, scenario))
        label_reason_parts.append(by_label_reason(validation, label, scenario))
        valid = validation[validation["valid_entry"] == True].copy()
        reasons = valid.groupby("exit_reason", dropna=False).size().reset_index(name="count")
        reasons.insert(0, "combo", label)
        reasons.insert(1, "scenario_id", scenario.scenario_id)
        reasons.insert(2, "scenario_name", scenario.name)
        reasons["ratio"] = reasons["count"] / reasons["count"].sum()
        reason_parts.append(reasons)
        detail_path = lab_dir / f"validation_v63_{scenario.label}_{stamp}.csv"
        validation.to_csv(detail_path, index=False)
        detail_paths.append(detail_path)

    year_path = lab_dir / f"base_on_base_v63_by_year_{stamp}.csv"
    reasons_path = lab_dir / f"base_on_base_v63_exit_reasons_{stamp}.csv"
    label_reason_path = lab_dir / f"base_on_base_v63_by_label_reason_{stamp}.csv"
    pd.concat(year_parts, ignore_index=True).to_csv(year_path, index=False)
    pd.concat(reason_parts, ignore_index=True).to_csv(reasons_path, index=False)
    pd.concat(label_reason_parts, ignore_index=True).to_csv(label_reason_path, index=False)

    logger.info("V6.3 汇总：%s", summary_path)
    logger.info("V6.3 分年：%s", year_path)
    logger.info("V6.3 卖出原因：%s", reasons_path)
    logger.info("V6.3 标签/结构原因拆分：%s", label_reason_path)
    logger.info("V6.3 明细：%s", [str(p) for p in detail_paths])


if __name__ == "__main__":
    main()
