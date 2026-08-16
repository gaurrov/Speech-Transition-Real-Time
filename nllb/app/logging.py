"""Structured logging setup for the NLLB service (JSON in production)."""
from __future__ import annotations

import logging

import structlog


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    logging.basicConfig(format="%(message)s", level=level)
    renderer = (
        structlog.processors.JSONRenderer()
        if fmt == "json"
        else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        cache_logger_on_first_use=True,
    )
