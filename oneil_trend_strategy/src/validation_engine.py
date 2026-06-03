from __future__ import annotations

import math
import pandas as pd
import polars as pl

import config


RET_DAYS = [1, 2, 3, 5, 10, 20, 40, 60]
MAX_MIN_DAYS = [5, 10, 20, 40, 60]
DD_DAYS = [20, 40, 60]


def _max_drawdown(values: list[float]) -> float | None:
    if not values:
        return None
    peak = values[0]
    mdd = 0.0
    for v in values:
        if pd.isna(v):
            continue
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1)
    return mdd


def _trend_exit(future: pd.DataFrame, entry_price: float) -> dict:
    highest_close = -math.inf
    closes = []
    for hold_idx, row in enumerate(future.itertuples(index=False), start=0):
        close = float(row.close)
        ma20 = getattr(row, "ma20")
        highest_close = max(highest_close, close)
        closes.append(close)
        reason = None
        if close < entry_price * 0.92:
            reason = "hard_stop"
        elif config.ENABLE_FAILED_BREAKOUT_EXIT and hold_idx <= 4 and close < entry_price:
            reason = "failed_breakout"
        elif close < highest_close * 0.90:
            reason = "trailing_stop"
        elif pd.notna(ma20) and hold_idx >= config.ENABLE_BREAK_MA20_EXIT_AFTER_DAYS and close < ma20:
            reason = "break_ma20"
        elif hold_idx >= config.MAX_HOLD_DAYS:
            reason = "timeout_exit"
        if reason:
            exit_idx = hold_idx + 1
            if exit_idx < len(future):
                exit_row = future.iloc[exit_idx]
                exit_date = exit_row["date"]
                exit_price = float(exit_row["open"])
            else:
                exit_row = future.iloc[hold_idx]
                exit_date = exit_row["date"]
                exit_price = float(exit_row["close"])
                reason = "data_end_exit"
            returns = [c / entry_price - 1 for c in closes]
            return {
                "trend_exit_signal_date": row.date,
                "trend_exit_date": exit_date,
                "trend_exit_price": exit_price,
                "trend_hold_days": hold_idx + 1,
                "trend_return": exit_price / entry_price - 1,
                "trend_exit_reason": reason,
                "trend_max_return_during_hold": max(returns) if returns else None,
                "trend_min_return_during_hold": min(returns) if returns else None,
                "trend_max_drawdown_during_hold": _max_drawdown(closes),
            }
    if len(future) == 0:
        return {"trend_exit_reason": "no_future_data"}
    row = future.iloc[-1]
    returns = [c / entry_price - 1 for c in closes]
    return {
        "trend_exit_signal_date": row["date"],
        "trend_exit_date": row["date"],
        "trend_exit_price": float(row["close"]),
        "trend_hold_days": len(future),
        "trend_return": float(row["close"]) / entry_price - 1,
        "trend_exit_reason": "data_end_exit",
        "trend_max_return_during_hold": max(returns) if returns else None,
        "trend_min_return_during_hold": min(returns) if returns else None,
        "trend_max_drawdown_during_hold": _max_drawdown(closes),
    }


def validate_signals(signals: pl.DataFrame, feature_df: pl.DataFrame, logger) -> pl.DataFrame:
    if signals.height == 0:
        return pl.DataFrame()
    pdf = feature_df.select(["date", "code", "open", "high", "low", "close", "ma20", "tradestatus"]).to_pandas()
    pdf = pdf.sort_values(["code", "date"])
    by_code = {code: g.reset_index(drop=True) for code, g in pdf.groupby("code", sort=False)}
    rows = []
    sig_pdf = signals.to_pandas().sort_values(["date", "code"])
    for s in sig_pdf.itertuples(index=False):
        prices = by_code.get(s.code)
        base = {
            "signal_date": s.date, "entry_date": None, "code": s.code, "industry_l1": s.industry_l1,
            "signal_type": s.signal_type, "pivot_price": s.pivot_price, "signal_close": s.close,
            "entry_price": None, "signal_score": s.signal_score, "valid_entry": False, "invalid_reason": None,
        }
        for col in [
            "weekly_filter_pass", "weekly_filter_mode", "weekly_pattern_ok", "weekly_trend_ok",
            "weekly_base_depth_30", "week_close_to_high_30", "week_close_to_high_52", "weekly_detail",
        ]:
            base[col] = getattr(s, col, None)
        if prices is None:
            base["invalid_reason"] = "code_missing_price_data"
            rows.append(base)
            continue
        idx_list = prices.index[prices["date"] == s.date].tolist()
        if not idx_list or idx_list[0] + 1 >= len(prices):
            base["invalid_reason"] = "no_next_trade_day"
            rows.append(base)
            continue
        sig_idx = idx_list[0]
        entry = prices.iloc[sig_idx + 1]
        if pd.isna(entry["open"]) or str(entry["tradestatus"]) != "1":
            base["entry_date"] = entry["date"]
            base["invalid_reason"] = "invalid_entry"
            rows.append(base)
            continue
        entry_price = float(entry["open"])
        future = prices.iloc[sig_idx + 1:].reset_index(drop=True)
        base.update({"entry_date": entry["date"], "entry_price": entry_price, "valid_entry": True, "invalid_reason": ""})
        for d in RET_DAYS:
            target = d
            base[f"ret_{d}d_open"] = float(future.iloc[target]["open"]) / entry_price - 1 if target < len(future) and pd.notna(future.iloc[target]["open"]) else None
        for d in MAX_MIN_DAYS:
            window = future.iloc[: d + 1]
            highs = (window["high"] / entry_price - 1).dropna()
            lows = (window["low"] / entry_price - 1).dropna()
            base[f"max_ret_{d}d"] = float(highs.max()) if not highs.empty else None
            base[f"min_ret_{d}d"] = float(lows.min()) if not lows.empty else None
        for d in DD_DAYS:
            closes = future.iloc[: d + 1]["close"].dropna().tolist()
            base[f"max_drawdown_{d}d"] = _max_drawdown(closes)
        base.update(_trend_exit(future, entry_price))
        rows.append(base)
    out = pl.from_pandas(pd.DataFrame(rows))
    logger.info("有效入场：%s / %s", out.filter(pl.col("valid_entry")).height, out.height)
    return out
