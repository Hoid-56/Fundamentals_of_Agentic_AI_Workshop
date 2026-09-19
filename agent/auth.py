"""
agent/auth.py — FROZEN. Login verification and account entitlements.

Deliberately NOT in tools.py. Nothing here is exposed to the model as a tool,
and nothing here is in the tool registry. Authentication is decided in code.

The model never adjudicates whether someone is authenticated. It is told the
answer, and — because of a decision made elsewhere in this system — it is also
told the password, which it did not need.
"""

from __future__ import annotations

import json

from agent.config import CREDENTIALS, USER_ACCOUNTS


def _store() -> dict:
    with open(CREDENTIALS, encoding="utf-8") as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith("_")}


def _accounts() -> dict:
    with open(USER_ACCOUNTS, encoding="utf-8") as f:
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


def profile_for(username: str) -> dict:
    """
    Segment and entitlements for a logged-in user.

    Entitlements are not a trust ranking. A business account may discuss
    confidential movements without re-authenticating but may not freeze a
    card; a retail account is the reverse. A guardrail that treats one segment
    as simply more privileged than the other will be wrong in one direction or
    the other, whichever it picks.
    """
    account = _accounts().get(username, {})
    return {
        "segment": account.get("segment", "retail"),
        "entitlements": dict(account.get("entitlements", {})),
    }


def known_users() -> list[str]:
    return sorted(_store().keys())


def customer_users() -> list[str]:
    """Usernames that are real customers, i.e. have an account as well."""
    return sorted(set(_store()) & set(_accounts()))
