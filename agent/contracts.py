"""
agent/contracts.py — FROZEN. The types crossing the boundary between the
harness and your submission.

These used to live in guardrails.py. They were moved here because a type that
both sides depend on cannot be owned by the side that is allowed to edit it:
redefining Decision would break the harness rather than your code, and the
failure would look like a grader bug.

Your guardrails.py imports these. It does not redefine them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Decision:
    """What a guardrail decided about one piece of content."""

    action: str                 # "allow" | "block" | "redact"
    content: Any = None         # replacement (block) or new content (redact)
    reason: str = ""            # shown in the grader report, never to the user

    @staticmethod
    def allow() -> "Decision":
        return Decision("allow")

    @staticmethod
    def block(replacement: str, reason: str = "") -> "Decision":
        return Decision("block", replacement, reason)

    @staticmethod
    def redact(new_content: Any, reason: str = "") -> "Decision":
        return Decision("redact", new_content, reason)


@dataclass
class Context:
    """
    Everything a guardrail knows about the session.

    history            prior turns, [{"role", "content"}, ...]
    authenticated      did the user log in at the terminal menu
    user_id            the logged-in username, or None
    password_verified  has the user re-entered their password THIS TURN.
                       Set in code by chatbot.py, never judged by the model.
    turn_index         0-based turn number in this conversation
    last_tool_result   whatever the previous tool returned
    scratch            free dict, persists for the whole conversation. The only
                       thing a guardrail may mutate.
    """

    history: list = field(default_factory=list)
    authenticated: bool = False
    user_id: str | None = None
    password_verified: bool = False
    turn_index: int = 0
    last_tool_result: Any = None
    scratch: dict = field(default_factory=dict)


# Stage names passed to execute_guardrails.
STAGE_INPUT = "input"
STAGE_TOOL = "tool"
STAGE_OUTPUT = "output"