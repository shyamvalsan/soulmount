"""Logging with secret redaction. Secrets never appear in logs (guardrail 5)."""

from __future__ import annotations

import logging
import re

# Patterns mirror scripts/leakcheck.sh; redact before anything reaches a log sink.
_SECRET_RE = re.compile(
    r"(sk-or-v[0-9]-[A-Za-z0-9]{8,}"
    r"|sk-ant-[A-Za-z0-9_-]{12,}"
    r"|sk-[A-Za-z0-9]{20,}"
    r"|[0-9]{8,10}:[A-Za-z0-9_-]{35}"
    r"|Bearer\s+[A-Za-z0-9._-]{16,})"
)


def redact(text: str) -> str:
    return _SECRET_RE.sub("***REDACTED***", text or "")


class _RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            record.args = tuple(
                redact(a) if isinstance(a, str) else a for a in record.args
            )
        return True


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        handler.addFilter(_RedactingFilter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger
