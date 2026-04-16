import os
import logging
from datetime import datetime

LOG_DIR = r"C:\CVNP-Python\Python Projects\Lab Deployment\logs"
LOG_FILE = os.path.join(LOG_DIR, "deployment.log")

# ANSI color codes for console output
COLORS = {
    "DEBUG":   "\033[94m",   # Blue
    "INFO":    "\033[92m",   # Green
    "WARNING": "\033[93m",   # Yellow
    "ERROR":   "\033[91m",   # Red
    "RESET":   "\033[0m",
}


class ColorFormatter(logging.Formatter):
    """Colorized console formatter."""

    def format(self, record):
        color = COLORS.get(record.levelname, COLORS["RESET"])
        reset = COLORS["RESET"]
        record.levelname = f"{color}{record.levelname}{reset}"
        return super().format(record)


def get_logger(name="acme_lab"):
    """
    Returns a configured logger with both file and console handlers.
    Safe to call multiple times — won't add duplicate handlers.
    """

    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # ---- File handler (plain text, full detail) ----
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            "[%(asctime)s] [%(levelname)s] %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
        logger.addHandler(fh)
    except Exception as e:
        print(f"[WARN] Could not open log file: {e}")

    # ---- Console handler (colorized) ----
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(ColorFormatter(
        "[%(asctime)s] %(levelname)s - %(message)s",
        datefmt="%H:%M:%S"
    ))
    logger.addHandler(ch)

    return logger


# ------------------------------------------------
# Module-level convenience logger
# ------------------------------------------------

log = get_logger()


def info(msg):    log.info(msg)
def warn(msg):    log.warning(msg)
def error(msg):   log.error(msg)
def debug(msg):   log.debug(msg)


def section(title):
    """Prints a prominent section header to both console and log."""
    bar = "=" * 50
    log.info(f"\n{bar}\n  {title}\n{bar}")


def step_start(name):
    log.info(f"[START] {name}")


def step_done(name):
    log.info(f"[DONE]  {name}")


def step_skip(name):
    log.info(f"[SKIP]  {name} — already completed")


def step_fail(name, reason=""):
    log.error(f"[FAIL]  {name}" + (f" — {reason}" if reason else ""))