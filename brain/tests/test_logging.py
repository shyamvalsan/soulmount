"""Secret redaction in logs (guardrail 5). Regression: secrets carried by NON-string
args (e.g. an httpx exception whose text holds a bot-token URL) must be redacted too —
the earlier filter only handled string args and leaked a Telegram token via an exception."""

from __future__ import annotations

import io
import logging

from soulmount_brain.logging_utils import _RedactingFilter, redact


def _fake_token() -> str:
    # built at runtime so no token-shaped literal sits in the source (leakcheck-safe)
    return "1234567890:" + "A" * 35


def test_redacts_token_in_exception_arg():
    tok = _fake_token()
    buf = io.StringIO()
    lg = logging.getLogger("test.redact.exc")
    lg.handlers = []
    h = logging.StreamHandler(buf)
    h.addFilter(_RedactingFilter())
    lg.addHandler(h)
    lg.setLevel(logging.INFO)
    lg.propagate = False
    lg.warning("getUpdates failed: %s", Exception(f"https://api.telegram.org/bot{tok}/getUpdates"))
    out = buf.getvalue()
    assert tok not in out
    assert "***REDACTED***" in out


def test_redact_plain_string():
    assert "***REDACTED***" in redact("token " + _fake_token())
