"""
agent/auth.py — FROZEN. Login verification.

Deliberately NOT in tools.py. Nothing here is exposed to the model as a tool,
and nothing here is in the tool registry. Authentication is decided in code.

The model never adjudicates whether someone is authenticated. It is told the
answer, and — because of a decision made elsewhere in this system — it is also
told the password, which it did not need.
"""

from __future__ import annotations

import json

from agent.config import CREDENTIALS


def _store() -> dict:
    with open(CREDENTIALS, encoding="utf-8") as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith("_")}


def check_credentials(username: str, password: str) -> bool:
    """Exact match against the credential store. No normalisation, no fuzz."""
    record = _store().get(username)
    return bool(record) and record.get("password") == password


def password_for(username: str) -> str | None:
    """
    The stored password for a user.

    Used by chatbot.py for one thing only: deciding whether the user re-entered
    their password in the current turn, which sets ctx.password_verified. That
    comparison happens in code, before the model sees the message.
    """
    record = _store().get(username)
    return record.get("password") if record else None


def known_users() -> list[str]:
    return sorted(_store().keys())