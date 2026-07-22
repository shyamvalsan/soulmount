"""Logging with secret redaction. Secrets never appear in logs (guardrail 5)."""

from __future__ import annotations

import logging
import re

# Kept in sync with scripts/leakcheck.sh SECRET_PATTERNS; redact before any log sink.
_SECRET_RE = re.compile(
    r"(sk-or-v[0-9]-[A-Za-z0-9]{8,}"        # OpenRouter
    r"|sk-ant-[A-Za-z0-9_-]{12,}"           # Anthropic
    r"|sk-[A-Za-z0-9]{20,}"                 # OpenAI-style
    r"|[0-9]{8,10}:[A-Za-z0-9_-]{35}"       # Telegram bot token
    r"|AKIA[0-9A-Z]{16}"                    # AWS
    r"|AIza[0-9A-Za-z_-]{35}"               # Google API key
    r"|GOCSPX-[A-Za-z0-9_-]{20,}"           # Google OAuth client secret
    r"|BSA[A-Za-z0-9_-]{24,}"               # Brave Search API key
    r"|ghp_[0-9A-Za-z]{36}"                 # GitHub PAT
    r"|Bearer\s+[A-Za-z0-9._-]{16,}"        # bearer header (incl. bare-hex BRAIN_API_KEY)
    r"|[0-9a-fA-F]{48,})"                   # long bare hex (e.g. an unprefixed BRAIN_API_KEY)
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


def redact_root_logging() -> None:
    """Belt-and-suspenders for entry points that may configure root logging: quiet the
    httpx/httpcore loggers (their INFO lines log the full request URL, incl. the Telegram
    bot token) and attach the redactor to the root logger + its handlers."""
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    root = logging.getLogger()
    if not any(isinstance(f, _RedactingFilter) for f in root.filters):
        root.addFilter(_RedactingFilter())
    for h in root.handlers:
        if not any(isinstance(f, _RedactingFilter) for f in h.filters):
            h.addFilter(_RedactingFilter())


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
