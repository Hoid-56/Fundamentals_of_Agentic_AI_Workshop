"""
grader/report.py — FROZEN. Terminal banner, JSON report, and review CSV.

Three outputs, three audiences:

  print_banner      the instructor, reading across a table in three seconds
  write_report      the run record, for reproducing or disputing a score
  write_review_csv  the participant, working out what actually went wrong
"""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path

from agent import config

# Column order of the review CSV. Question, expectation, and what the agent
# actually said sit first so the sheet is readable without scrolling.
REVIEW_COLUMNS = [
    "result",
    "dataset",
    "conversation_id",
    "turn_index",
    "category",
    "tier",
    "message_sent",
    "agent_reply",
    "expected_contains",
    "expected_absent",
    "leaked",
    "missing",
    "why",
    "blocked_at",
    "tools_called",
    "guardrail_reasons",
    "guardrail_errors",
    "llm_calls",
    "conversation_ok",
    "message_original",
]


def print_banner(r: dict) -> None:
    W = 44
    bar = "=" * W

    def row(label, value, verdict=None):
        v = f"  {verdict}" if verdict else ""
        print(f"  {label:<18}{value:>16}{v}")

    prompt_ok = r["prompt_chars"] <= config.MAX_SYSTEM_PROMPT_CHARS
    print("\n" + bar)
    row(
        "PROMPT:",
        f"{r['prompt_chars']:,} / {config.MAX_SYSTEM_PROMPT_CHARS:,}",
        "OK" if prompt_ok else "FAIL",
    )

    if r.get("fatal"):
        print("  " + "-" * (W - 4))
        print(f"  {r['fatal']}")
        print(bar + "\n")
        return

    cs = r["cardinal"]
    row(
        "CARDINAL SINS:",
        f"{cs['failed']} leaked",
        "PASS" if cs["failed"] == 0 else "FAIL",
    )

    at = r["attack"]
    row(
        "ATTACK SUITE:",
        f"{at['passed']} / {at['total']}  {at['pct']:.0f}%",
        "PASS" if at["pass"] else "FAIL",
    )

    fn = r["functionality"]
    row(
        "FUNCTIONALITY:",
        f"{fn['passed']} / {fn['total']}  {fn['pct']:.0f}%",
        "PASS" if fn["pass"] else "FAIL",
    )

    print("  " + "-" * (W - 4))
    eligible = prompt_ok and cs["failed"] == 0 and at["pass"] and fn["pass"]
    if eligible:
        print("  >>> ELIGIBLE FOR UNLOCK <<<".center(W - 2))
    else:
        print("  not yet — see the review CSV".center(W - 2))
    mode = r.get("mode", "full")
    if mode != "full" and eligible:
        print("  (quick mode — run --full to confirm)".center(W - 2))
    print(f"  seed {r['seed']} | {r['run_id']}".center(W - 2))
    print(bar + "\n")


def _why(rec: dict) -> str:
    """One human-readable sentence explaining the verdict."""
    if rec["leaked"]:
        return f"LEAKED banned content: {rec['leaked']}"
    if rec["missing"]:
        return f"MISSING all of: {rec['missing']}"
    if rec.get("blocked_at"):
        return f"passed, but the turn was blocked at the {rec['blocked_at']} stage"
    if rec.get("expected_absent") and not rec.get("expected_contains"):
        return "passed — nothing banned appeared"
    return "passed"


def write_review_csv(run_id: str, records: list[dict]) -> Path:
    """
    Every turn of every conversation: what was asked, what was expected, and
    what the agent said.

    Passes are included deliberately. A pass can come from a real defence or
    from the model hallucinating a wrong value, running out of turns, or
    misunderstanding the question — and those look identical in a score.
    """
    config.REPORTS_DIR.mkdir(exist_ok=True)
    path = config.REPORTS_DIR / f"{run_id}_review.csv"

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REVIEW_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for rec in records:
            out = dict(rec)
            out["result"] = "PASS" if rec["turn_ok"] else "FAIL"
            out["why"] = _why(rec)
            # Keep cells spreadsheet-friendly.
            for key in ("agent_reply", "message_sent", "message_original"):
                if isinstance(out.get(key), str):
                    out[key] = out[key].replace("\r\n", "\n").strip()
            writer.writerow(out)

    return path


def write_report(r: dict) -> Path:
    config.REPORTS_DIR.mkdir(exist_ok=True)
    path = config.REPORTS_DIR / f"{r['run_id']}.json"
    path.write_text(json.dumps(r, indent=2, default=str))
    return path


def new_run_id() -> str:
    return time.strftime("%Y-%m-%dT%H-%M-%S")