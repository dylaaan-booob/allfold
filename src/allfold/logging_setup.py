"""Application logging configuration."""

from __future__ import annotations

import logging
import os
import sys

LOGGER_NAME = "allfold"
_HANDLER_MARKER = "_allfold_handler"


def effective_log_level(saved: str = "INFO") -> str:
    """An explicit process override wins; otherwise use the saved setting."""
    value = os.environ.get('ALLFOLD_LOG_LEVEL', saved).upper()
    if value == 'WARN':
        value = 'WARNING'
    return value if value in {'DEBUG', 'INFO', 'WARNING', 'ERROR'} else 'INFO'


def configure_logging(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    for handler in tuple(logger.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            logger.removeHandler(handler)
            handler.close()

    handler = logging.StreamHandler(sys.stderr)
    setattr(handler, _HANDLER_MARKER, True)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(effective_log_level(level))
    logger.propagate = False
    return logger
