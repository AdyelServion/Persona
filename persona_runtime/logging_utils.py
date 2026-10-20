"""Structured logging helpers. Never log secrets or full private message bodies at info."""

from __future__ import annotations

import logging
import sys
from typing import Any


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(
    logger: logging.Logger,
    message: str,
    *,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    safe = {k: v for k, v in fields.items() if k.lower() not in {"api_key", "password", "secret", "token", "ngrok_key", "openai_api_key", "mongodb_uri"}}
    if safe:
        logger.log(level, "%s | %s", message, " ".join(f"{k}={v}" for k, v in safe.items()))
    else:
        logger.log(level, message)
