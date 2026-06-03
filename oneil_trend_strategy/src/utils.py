from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path


def setup_logger(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("oneil_trend_strategy")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    logger.addHandler(stream)
    file_handler = logging.FileHandler(log_dir / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log", encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)
    return logger


def normalize_date(value: str) -> str:
    return str(value).replace("-", "")


def normalize_code(value: str) -> str:
    s = str(value).strip()
    if not s or s.lower() == "nan":
        return s
    if "." in s:
        left, right = s.split(".", 1)
        if left.lower() in {"sh", "sz", "bj"}:
            return f"{right}.{left.upper()}"
        return f"{left}.{right.upper()}"
    if s.startswith("6"):
        return f"{s}.SH"
    if s.startswith(("0", "3")):
        return f"{s}.SZ"
    if s.startswith(("4", "8", "9")):
        return f"{s}.BJ"
    return s


def ensure_output_dirs(output_dir: Path) -> None:
    for name in ["signals", "validation", "stats", "logs"]:
        (output_dir / name).mkdir(parents=True, exist_ok=True)
