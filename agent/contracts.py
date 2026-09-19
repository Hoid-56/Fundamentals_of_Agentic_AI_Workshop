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
    segment            "retail" | "business". Set at login from the account
    entitlements       what this account is allowed to do. Neither segment is
                       simply more trusted than the other — each can do
                       something the other cannot, so "business = privileged"
                       is a wrong rule, not a shortcut
    password_verified  has the user re-entered their password THIS TURN.
                       Set in code by chatbot.py, never judged by the model
    turn_index         0-based turn number in this conversation
    last_tool_result   whatever the previous tool returned, AFTER guardrails
    scratch            free dict, persists for the whole conversation. The only
                       thing a guardrail may mutate
    """

    history: list = field(default_factory=list)
    authenticated: bool = False
    user_id: str | None = None
    segment: str = "retail"
    entitlements: dict = field(default_factory=dict)
    password_verified: bool = False
    turn_index: int = 0
    last_tool_result: Any = None
    scratch: dict = field(default_factory=dict)

    def may(self, entitlement: str) -> bool:
        """Convenience: is this account entitled to `entitlement`?"""
        return bool(self.entitlements.get(entitlement))


# Stage names passed to execute_guardrails.
STAGE_INPUT = "input"
STAGE_TOOL = "tool"
STAGE_TOOL_RESULT = "tool_result"
STAGE_OUTPUT = "output"

STAGES = (STAGE_INPUT, STAGE_TOOL, STAGE_TOOL_RESULT, STAGE_OUTPUT)

VALID_ACTIONS = {"allow", "block", "redact"}


@dataclass
class GuardrailEvent:
    """One invocation of execute_guardrails, recorded for the report."""

    stage: str
    action: str
    reason: str = ""
    elapsed_ms: float = 0.0
    error: str | None = None          # guardrail raised, or returned garbage
    over_budget: bool = False         # exceeded MAX_GUARDRAIL_MS


@dataclass
class TurnResult:
    """
    What one turn produced.

    `reply` is what the user sees and what the grader scans for leaks.

    `tool_results` is what the model was actually shown after the tool_result
    guardrail ran. It is scored separately, because a secret that reaches the
    model's context has already escaped even if it never reaches the user: it
    stays in the transcript for every later turn of the conversation.
    """

    reply: str
    events: list[GuardrailEvent] = field(default_factory=list)
    tool_calls: list = field(default_factory=list)      # [(name, arguments, status)]
    tool_results: list = field(default_factory=list)    # [(name, result_as_seen)]
    llm_calls: int = 0
    blocked_at: str | None = None                       # stage that ended the turn
    hit_iteration_cap: bool = False

    @property
    def guardrail_errors(self) -> list[str]:
        return [e.error for e in self.events if e.error]
