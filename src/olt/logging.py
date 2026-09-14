"""Logging and error reporting for omarchy-live-translator.

Every component logs through this module. Logs go to stderr (visible in the
systemd journal) and, when a log directory is configured, to a rotating file.
Uncaught exceptions are reported with a full traceback and a clear, greppable
tag so bug reports can be filed easily.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import traceback
from pathlib import Path

APP_NAME = "omarchy-live-translator"

# A single greppable tag for all messages, so `journalctl -t` and `grep` work.
LOGGER_NAME = "olt"

_logger: logging.Logger | None = None


def _build_logger(log_dir: Path | None, level: str) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level.upper())
    logger.propagate = False

    # Idempotent: drop handlers from a previous setup() call.
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    # stderr handler (systemd journal picks this up)
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(fmt)
    logger.addHandler(stream)

    if log_dir is not None:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                log_dir / "olt.log",
                maxBytes=1_000_000,
                backupCount=3,
                encoding="utf-8",
            )
            file_handler.setFormatter(fmt)
            logger.addHandler(file_handler)
        except OSError as exc:  # logging must never crash the app
            logger.warning("could not open log file in %s: %s", log_dir, exc)

    return logger


def setup(log_dir: Path | str | None = None, level: str = "INFO") -> logging.Logger:
    """Initialise logging. Call once at startup."""
    global _logger
    if isinstance(log_dir, str):
        log_dir = Path(log_dir)
    _logger = _build_logger(log_dir, level)
    return _logger


def get() -> logging.Logger:
    """Return the shared logger, initialising with defaults if needed."""
    global _logger
    if _logger is None:
        _logger = _build_logger(None, "INFO")
    return _logger


def log_uncaught(exc_type, exc_value, exc_tb) -> None:
    """sys.excepthook: report uncaught exceptions with a full traceback."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    logger = get()
    logger.error(
        "UNCAUGHT EXCEPTION (%s): %s\n%s",
        exc_type.__name__,
        exc_value,
        "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
    )


def install_hooks() -> None:
    """Install global exception hooks so nothing fails silently."""
    sys.excepthook = log_uncaught
    threading_excepthook = getattr(sys, "excepthook", None)
    if threading_excepthook is not None:
        # asyncio and threads route through here; keep the default behaviour
        # but make sure our logger sees the error.
        import threading

        def _thread_hook(args):
            logger = get()
            logger.error(
                "THREAD EXCEPTION in %s: %s",
                args.thread.name if args.thread else "?",
                args.exc_type.__name__ if args.exc_type else "?",
            )
            if args.exc_value:
                logger.error(
                    "%s",
                    "".join(
                        traceback.format_exception(
                            args.exc_type, args.exc_value, args.exc_traceback
                        )
                    ),
                )

        threading.excepthook = _thread_hook


def report_error(context: str, exc: BaseException | None = None) -> str:
    """Log an error and return a short human-readable message.

    Used by components so the overlay can show a concise hint while the full
    detail lands in the log for bug reports.
    """
    logger = get()
    if exc is not None:
        logger.error("%s failed: %s\n%s", context, exc, traceback.format_exc())
    else:
        logger.error("%s failed", context)
    return f"{context} failed — see log for details"
