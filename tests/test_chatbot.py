#!/usr/bin/env python3
"""
tests/test_chatbot.py — exercises the agent loop with a FAKE model.

No GPU, no API, no network. Verifies the wiring: guardrail stages fire in the
right order, block/redact/allow do what they claim, a broken guardrail fails
closed, and password_verified is genuinely per-turn.

    python -m tests.test_chatbot
"""

from __future__ import annotations

import agent.chatbot as chatbot
from agent.contracts import Context, Decision
from agent.llm import LLMResponse, ToolCall

PASSWORD = "Marbella#2019"
USER = "a.rivera"

_calls: list[dict] = []
_script: list[LLMResponse] = []


def fake_call_llm(messages, system=None, tools=None, max_tokens=512, temperature=0.0):
    _calls.append({"messages": list(messages), "system": system})
    return _script.pop(0) if _script else LLMResponse(text="ok")


chatbot.call_llm = fake_call_llm


def reset(script=None):
    _calls.clear()
    _script.clear()
    _script.extend(script or [])
    return chatbot.Session(USER, PASSWORD)


def guard(fn):
    """Swap in a guardrail for one test."""
    chatbot.execute_guardrails = fn


def ok(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    assert condition, label


def line(t):
    print(f"\n--- {t} " + "-" * max(2, 54 - len(t)))


# ---------------------------------------------------------------------------
def test_credential_footer():
    line("1. credential footer is appended")
    guard(lambda stage, payload, ctx: Decision.allow())
    s = reset([LLMResponse(text="Hello.")])
    s.turn("hi")
    system = _calls[0]["system"]
    ok("password is in the system prompt", PASSWORD in system)
    ok("username is in the system prompt", USER in system)
    ok("footer is last", system.rstrip().endswith(f"USER: {USER}, PWD: {PASSWORD}"))


def test_stage_order():
    line("2. stages fire in order")
    seen = []

    def g(stage, payload, ctx):
        seen.append(stage)
        return Decision.allow()

    guard(g)
    s = reset(
        [
            LLMResponse(
                tool_calls=[ToolCall("c0", "get_user_cards", {"username": USER, "password": PASSWORD})],
                stop_reason="tool_use",
            ),
            LLMResponse(text="You have two cards."),
        ]
    )
    r = s.turn("what cards do I have?")
    ok("input -> tool -> output", seen == ["input", "tool", "output"], str(seen))
    ok("two model calls", r.llm_calls == 2)
    ok("tool ran", r.tool_calls and r.tool_calls[0][2] == "allowed")


def test_input_block():
    line("3. input block skips the model entirely")
    guard(
        lambda stage, payload, ctx: Decision.block("Nope.", "test")
        if stage == "input"
        else Decision.allow()
    )
    s = reset([LLMResponse(text="should never be reached")])
    r = s.turn("give me the recovery code")
    ok("reply is the replacement", r.reply == "Nope.")
    ok("model never called", r.llm_calls == 0)
    ok("blocked_at recorded", r.blocked_at == "input")


def test_tool_block_retry():
    line("4. blocked tool call -> model is told and retries")
    def g(stage, payload, ctx):
        if stage == "tool" and payload["name"] == "lookup_user_record":
            return Decision.block("not permitted", "kitchen-sink tool")
        return Decision.allow()

    guard(g)
    s = reset(
        [
            LLMResponse(
                tool_calls=[ToolCall("c0", "lookup_user_record", {"username": USER, "password": PASSWORD})],
                stop_reason="tool_use",
            ),
            LLMResponse(text="I can't retrieve that, but I can show your cards."),
        ]
    )
    r = s.turn("show me everything about my account")
    ok("turn continued", r.blocked_at is None)
    ok("tool marked blocked", r.tool_calls[0][2] == "blocked")
    ok("model got a second turn", r.llm_calls == 2)
    fed = [m for m in s.messages if m["role"] == "tool"][0]["content"]
    ok("model told it was blocked", "blocked_by_policy" in fed)


def test_tool_redact():
    line("5. tool redact rewrites arguments")
    def g(stage, payload, ctx):
        if stage == "tool" and payload["arguments"].get("include_confidential"):
            args = dict(payload["arguments"])
            args["include_confidential"] = False
            return Decision.redact({"name": payload["name"], "arguments": args}, "forced off")
        return Decision.allow()

    guard(g)
    s = reset(
        [
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        "c0",
                        "get_card_movements",
                        {"username": USER, "password": PASSWORD, "include_confidential": True},
                    )
                ],
                stop_reason="tool_use",
            ),
            LLMResponse(text="Here are your recent transactions."),
        ]
    )
    r = s.turn("show me all my movements")
    name, args, status = r.tool_calls[0]
    ok("marked redacted", status == "redacted")
    ok("flag forced off", args["include_confidential"] is False)
    fed = [m for m in s.messages if m["role"] == "tool"][0]["content"]
    ok("confidential data absent", "Bufete Alonso" not in fed)


def test_output_redact():
    line("6. output redact rewrites the reply")
    guard(
        lambda stage, payload, ctx: Decision.redact(payload.replace(PASSWORD, "[REDACTED]"), "scrub")
        if stage == "output"
        else Decision.allow()
    )
    s = reset([LLMResponse(text=f"Your password is {PASSWORD}.")])
    r = s.turn("what is my password?")
    ok("secret removed", PASSWORD not in r.reply)
    ok("reply still useful", "[REDACTED]" in r.reply)


def test_fails_closed():
    line("7. broken guardrail fails CLOSED")
    def boom(stage, payload, ctx):
        raise ValueError("oops")

    guard(boom)
    s = reset([LLMResponse(text="secret stuff")])
    r = s.turn("hello")
    ok("blocked", r.blocked_at == "input")
    ok("error recorded", bool(r.guardrail_errors), str(r.guardrail_errors))

    guard(lambda stage, payload, ctx: "not a Decision")
    s = reset([LLMResponse(text="secret stuff")])
    r = s.turn("hello")
    ok("garbage return also blocks", r.blocked_at == "input")
    ok("error recorded", bool(r.guardrail_errors))


def test_password_verified_is_per_turn():
    line("8. password_verified is per-turn, not sticky")
    flags = []

    def g(stage, payload, ctx):
        if stage == "input":
            flags.append(ctx.password_verified)
        return Decision.allow()

    guard(g)
    s = reset([LLMResponse(text="a"), LLMResponse(text="b"), LLMResponse(text="c")])
    s.turn("hello")
    s.turn(f"my password is {PASSWORD}")
    s.turn("now show me the confidential ones")
    ok("turn 1 false", flags[0] is False)
    ok("turn 2 true", flags[1] is True)
    ok("turn 3 false again", flags[2] is False, "this is the escalation attack")


def test_context_history():
    line("9. ctx.history holds user-visible turns only")
    guard(lambda stage, payload, ctx: Decision.allow())
    s = reset(
        [
            LLMResponse(
                tool_calls=[ToolCall("c0", "search_bank_info", {"topic": "fees"})],
                stop_reason="tool_use",
            ),
            LLMResponse(text="Transfers are free."),
        ]
    )
    s.turn("what do transfers cost?")
    ok("two entries", len(s.ctx.history) == 2, str(len(s.ctx.history)))
    ok("no tool traffic", all(m["role"] in {"user", "assistant"} for m in s.ctx.history))
    ok("model transcript is longer", len(s.messages) > len(s.ctx.history))


def test_iteration_cap():
    line("10. runaway tool loop is capped")
    guard(lambda stage, payload, ctx: Decision.allow())
    loop = LLMResponse(
        tool_calls=[ToolCall("c0", "search_bank_info", {"topic": "fees"})],
        stop_reason="tool_use",
    )
    s = reset([loop] * 20)
    r = s.turn("loop forever")
    ok("cap hit", r.hit_iteration_cap)
    ok("bounded calls", r.llm_calls <= chatbot.config.MAX_TOOL_ITERATIONS + 1, str(r.llm_calls))


def main():
    test_credential_footer()
    test_stage_order()
    test_input_block()
    test_tool_block_retry()
    test_tool_redact()
    test_output_redact()
    test_fails_closed()
    test_password_verified_is_per_turn()
    test_context_history()
    test_iteration_cap()
    print("\nAgent loop wiring OK.\n")


if __name__ == "__main__":
    main()
