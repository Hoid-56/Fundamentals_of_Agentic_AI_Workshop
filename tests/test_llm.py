#!/usr/bin/env python3
"""
test_llm.py — proves the wrapper is actually agnostic.

Run this against every backend you intend to support. If all of them print the
same canonical shapes, chatbot.py will not notice the swap.

    LLM_BACKEND=local     python test_llm.py
    LLM_BACKEND=anthropic python test_llm.py
    LLM_BACKEND=bedrock   python test_llm.py
"""

import os
import time

from dotenv import load_dotenv

load_dotenv()

from agent.llm import call_llm, call_llm_many  # noqa: E402

TOOLS = [
    {
        "name": "get_card_balance",
        "description": "Retrieve the current balance for a user's card.",
        "parameters": {
            "type": "object",
            "properties": {
                "card_last4": {"type": "string", "description": "Last 4 digits."}
            },
            "required": ["card_last4"],
        },
    }
]

SYSTEM = "You are a banking assistant. Begin every reply with [BANK]. Be brief."


def line(t):
    print(f"\n--- {t} " + "-" * (54 - len(t)))


def main():
    print(f"backend : {os.getenv('LLM_BACKEND', 'local')}")
    print(f"model   : {os.getenv('LLM_MODEL', '(default)')}")

    # 1. plain text
    line("1. text completion")
    r = call_llm(
        messages=[{"role": "user", "content": "What are your opening hours?"}],
        system=SYSTEM,
    )
    print(f"text        : {r.text[:120]}")
    print(f"stop_reason : {r.stop_reason}")
    print(f"usage       : {r.usage}")
    assert r.text, "empty response"
    assert not r.wants_tool

    # 2. tool call
    line("2. tool call")
    msgs = [{"role": "user", "content": "What is the balance on my card ending 4821?"}]
    r = call_llm(messages=msgs, system=SYSTEM, tools=TOOLS)
    print(f"wants_tool  : {r.wants_tool}")
    for c in r.tool_calls:
        print(f"  call      : {c.name}({c.arguments})  id={c.id}")
        assert isinstance(c.arguments, dict), "arguments must be a dict, not a string"
    assert r.wants_tool, "model did not call the tool"

    # 3. full round trip — the part that usually breaks on a swap
    line("3. tool result round trip")
    call = r.tool_calls[0]
    msgs += [
        {"role": "assistant", "content": r.text, "tool_calls": r.tool_calls},
        {"role": "tool", "tool_call_id": call.id, "content": '{"balance": "1240.55 EUR"}'},
    ]
    r2 = call_llm(messages=msgs, system=SYSTEM, tools=TOOLS)
    print(f"final       : {r2.text[:160]}")
    assert r2.text, "no final answer after tool result"
    # Weak assertions hide real failures. The model must actually USE the
    # result, not describe the function that produced it.
    used = "1240" in r2.text or "1,240" in r2.text
    print(f"used result : {used}")
    assert used, "model ignored the tool result — round trip is broken"

    # 4. determinism
    line("4. determinism (temperature=0)")
    q = [{"role": "user", "content": "Explain in one sentence how to report a lost card."}]
    a = call_llm(messages=q, system=SYSTEM).text
    b = call_llm(messages=q, system=SYSTEM).text
    print(f"identical   : {a == b}")
    if a != b:
        print("  WARNING: scoring will not be reproducible on this backend.")

    # 5. batching
    line("5. batch throughput")
    reqs = [
        {"messages": [{"role": "user", "content": f"Say the number {i}."}], "system": SYSTEM}
        for i in range(8)
    ]
    t0 = time.time()
    batch = call_llm_many(reqs, max_workers=8)
    dt = time.time() - t0
    print(f"8 calls in  : {dt:.1f}s  ({dt / 8:.2f}s per call)")
    print(f"ordered ok  : {len(batch) == 8 and all(x.text for x in batch)}")
    print(f"est. 400    : ~{dt / 8 * 400 / 60:.1f} min at this rate")

    print("\nAll canonical shapes OK for this backend.\n")


if __name__ == "__main__":
    main()