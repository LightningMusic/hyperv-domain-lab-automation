"""
utils/logger.py
Centralised logging with console colour and file output.
Log directory is resolved relative to this file so it works from any CWD.
"""
import os
import logging
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LOG_DIR      = _PROJECT_ROOT / "logs"
_LOG_FILE     = _LOG_DIR / "deployment.log"

COLORS = {
    "DEBUG":   "\033[94m",
    "INFO":    "\033[92m",
    "WARNING": "\033[93m",
    "ERROR":   "\033[91m",
    "RESET":   "\033[0m",
}


class ColorFormatter(logging.Formatter):
    def format(self, record):
        c = COLORS.get(record.levelname, COLORS["RESET"])
        record.levelname = f"{c}{record.levelname:<7}{COLORS['RESET']}"
        return super().format(record)


def get_logger(name: str = "acme_lab") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # File handler
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(str(_LOG_FILE), encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            "[%(asctime)s] [%(levelname)s] %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
        logger.addHandler(fh)
    except Exception as e:
        print(f"[WARN] Log file unavailable: {e}")

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(ColorFormatter(
        "[%(asctime)s] %(levelname)s %(message)s",
        datefmt="%H:%M:%S"
    ))
    logger.addHandler(ch)

    return logger


# Module-level convenience shortcuts
log = get_logger()


def info(msg):   log.info(msg)
def warn(msg):   log.warning(msg)
def error(msg):  log.error(msg)
def debug(msg):  log.debug(msg)


def section(title: str):
    bar = "=" * 55
    log.info(f"\n{bar}\n  {title}\n{bar}")


def step_start(n): log.info(f"[START] {n}")
def step_done(n):  log.info(f"[DONE]  {n}")
def step_skip(n):  log.info(f"[SKIP]  {n}")
def step_fail(n, r=""): log.error(f"[FAIL]  {n}" + (f" — {r}" if r else ""))