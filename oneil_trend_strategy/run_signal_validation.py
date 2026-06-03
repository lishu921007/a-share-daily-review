#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import config
from src.data_loader import load_daily_data, load_universe
from src.feature_engineering import add_daily_features
from src.industry_features import add_industry_features
from src.signal_engine import generate_signals
from src.statistics import write_statistics, write_v1_v2_compare
from src.utils import ensure_output_dirs, normalize_date, setup_logger
from src.validation_engine import validate_signals
from src.weekly_features import add_weekly_features, join_weekly_features_to_daily
from src.weekly_filter import add_weekly_filter_columns


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="欧奈尔多形态趋势信号有效性验证")
    p.add_argument("--daily_dir", type=Path, default=config.DAILY_DATA_DIR)
    p.add_argument("--universe_dir", type=Path, default=config.UNIVERSE_DIR)
    p.add_argument("--start_date", default=config.START_DATE)
    p.add_argument("--end_date", default=config.END_DATE)
    p.add_argument("--output_dir", type=Path, default=config.OUTPUT_DIR)
    p.add_argument("--weekly_filter_mode", choices=["off", "loose", "strict"], default=config.WEEKLY_FILTER_MODE)
    p.add_argument("--use_weekly_filter", action="store_true", default=config.USE_WEEKLY_FILTER)
    p.add_argument("--compare_v1_v2", action="store_true", help="run V1 daily-only and V2 weekly-loose, then write compare csv")
    return p.parse_args()


def run_once(features, start_date: str, end_date: str, industry_enabled: bool, output_dir: Path, stamp: str, logger):
    signals = generate_signals(features, normalize_date(start_date), normalize_date(end_date), industry_enabled, logger)
    signal_path = output_dir / "signals" / f"signals_{stamp}.csv"
    signals.write_csv(signal_path)
    logger.info("信号明细输出：%s", signal_path)

    validation = validate_signals(signals, features, logger)
    validation_path = output_dir / "validation" / f"signal_validation_{stamp}.csv"
    validation.write_csv(validation_path)
    logger.info("验证明细输出：%s", validation_path)

    stat_paths = write_statistics(validation, output_dir, stamp, logger)
    logger.info("完成。signals=%s validation=%s stats=%s", signal_path, validation_path, stat_paths)
    return signals, validation, {"signals": signal_path, "validation": validation_path, **stat_paths}


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir if args.output_dir.is_absolute() else (Path.cwd() / args.output_dir).resolve()
    ensure_output_dirs(output_dir)
    logger = setup_logger(output_dir / "logs")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    logger.info("当前工作目录：%s", Path.cwd())
    logger.info("子项目路径：%s", config.PROJECT_DIR)
    logger.info("日 K 数据路径：%s", args.daily_dir.resolve())
    logger.info("股票池路径：%s", args.universe_dir.resolve())
    logger.info("验证区间：%s 至 %s", args.start_date, args.end_date)
    logger.info("启用过滤：基础过滤、宽松趋势过滤、行业后30%%剔除（如有行业字段）")
    logger.info("周线过滤参数：use=%s mode=%s compare=%s", args.use_weekly_filter, args.weekly_filter_mode, args.compare_v1_v2)

    universe = load_universe(args.universe_dir, logger)
    daily = load_daily_data(args.daily_dir, universe, args.start_date, args.end_date, logger)
    features = add_daily_features(daily, logger)
    features, industry_enabled = add_industry_features(features, logger)
    weekly = add_weekly_features(features, logger)
    features = join_weekly_features_to_daily(features, weekly, logger)

    if args.compare_v1_v2:
        config.USE_WEEKLY_FILTER = False
        config.WEEKLY_FILTER_MODE = "off"
        features_v1 = add_weekly_filter_columns(features, "off")
        logger.info("开始 V1 daily-only 验证。")
        _, v1_validation, _ = run_once(features_v1, args.start_date, args.end_date, industry_enabled, output_dir, f"{stamp}_v1_daily_only", logger)

        config.USE_WEEKLY_FILTER = True
        config.WEEKLY_FILTER_MODE = "loose"
        features_v2 = add_weekly_filter_columns(features, "loose")
        logger.info("开始 V2 weekly-loose 验证。")
        _, v2_validation, _ = run_once(features_v2, args.start_date, args.end_date, industry_enabled, output_dir, f"{stamp}_v2_weekly_loose", logger)

        compare_path = write_v1_v2_compare(v1_validation, v2_validation, output_dir, stamp)
        logger.info("V1/V2 对比输出：%s", compare_path)
        return

    config.USE_WEEKLY_FILTER = args.use_weekly_filter
    config.WEEKLY_FILTER_MODE = args.weekly_filter_mode if args.use_weekly_filter else "off"
    features = add_weekly_filter_columns(features, config.WEEKLY_FILTER_MODE)
    run_once(features, args.start_date, args.end_date, industry_enabled, output_dir, stamp, logger)


if __name__ == "__main__":
    main()
