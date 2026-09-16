"""
guardrails.py — YOUR FILE. Edit freely.

This is one of only two files you submit. `chatbot.py` imports
`execute_guardrails` from here and calls it at three points in every turn.
The signature below is FROZEN: do not change its name, parameters, or return
type, or the harness will not run your submission.

---------------------------------------------------------------------------
THE THREE STAGES
---------------------------------------------------------------------------
Your function is called three times per turn. `stage` tells you where you are:

  "input"   The raw user message, BEFORE it reaches the model.
            Blocking here means the model is never called.

  "tool"    A tool call the model wants to make, BEFORE it executes.
            `payload` is a dict: {"name": str, "arguments": dict}
            Blocking here means the tool never runs and the model is told so.

  "output"  The model's draft reply, BEFORE the user sees it.
            This is your last line of defence.

You do not have to act at every stage. Deciding WHERE to intervene is most of
the exercise.

---------------------------------------------------------------------------
WHAT YOU GET (ctx)
---------------------------------------------------------------------------
ctx.history            list[dict]  prior turns, [{"role","content"}, ...]
ctx.authenticated      bool        did the user log in this session
ctx.user_id            str | None  logged-in user, else None
ctx.password_verified  bool        has the user re-entered their password
                                   THIS TURN (not just at login)
ctx.turn_index         int         0-based turn number in this conversation
ctx.last_tool_result   Any | None  what the previous tool returned
ctx.scratch            dict        free dict, persists across the whole
                                   conversation. Use it to remember that a
                                   user already tried something.

---------------------------------------------------------------------------
WHAT YOU RETURN
---------------------------------------------------------------------------
A Decision. Three actions:

  Decision.allow()
      Let it through unchanged.

  Decision.block(replacement, reason="...")
      Stop it. `replacement` is what the user sees instead.
      At stage "tool", `replacement` is the message handed back to the model.

  Decision.redact(new_content, reason="...")
      Let it through, but modified. Use this to strip a secret out of an
      otherwise useful reply rather than killing the whole response.

`reason` is not shown to the user. It appears in the grader report, so you
can see which rule fired on which test. Use it — it is the difference between
debugging in 30 seconds and debugging in 10 minutes.

---------------------------------------------------------------------------
RULES
---------------------------------------------------------------------------
1. NO network calls. No LLM calls inside guardrails. Deterministic logic only.
   (Real reason: your guardrail must be cheap and reproducible. A guardrail
   that costs a model call per turn doubles your latency and your bill.)
2. Standard library only, plus `re`. No extra pip installs.
3. Pure function. Do not mutate anything except `ctx.scratch`.
4. Must return in under 100ms.
5. Do not read the dataset files. The grader runs against a HIDDEN set with
   the same attack families and different wording — matching on literal
   strings from the public set will not generalise.

---------------------------------------------------------------------------
WHERE TO START
---------------------------------------------------------------------------
Read `pentesting_public.csv` and `functionality.csv` first. Work out what the
agent must protect and what it must still be able to do. Then decide which
stage each rule belongs at.

Hint from the baseline run: the model has been observed to leak a secret while
simultaneously claiming it cannot. Checking that a reply *sounds* like a
refusal is not the same as checking that it *is* one.
"""

import re
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# FROZEN — do not modify
# ---------------------------------------------------------------------------
@dataclass
class Decision:
    action: str                 # "allow" | "block" | "redact"
    content: Any = None         # replacement text (block) or new content (redact)
    reason: str = ""

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
    history: list = field(default_factory=list)
    authenticated: bool = False
    user_id: str | None = None
    password_verified: bool = False
    turn_index: int = 0
    last_tool_result: Any = None
    scratch: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# YOUR CODE BELOW
# ---------------------------------------------------------------------------
def execute_guardrails(stage: str, payload: Any, ctx: Context) -> Decision:
    """
    stage   : "input" | "tool" | "output"
    payload : str for "input" and "output"
              dict {"name","arguments"} for "tool"
    ctx     : Context (see docstring)
    returns : Decision
    """
    # TODO: this is your job.
    return Decision.allow()