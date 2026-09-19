#!/usr/bin/env python3
"""
scripts/run_ladder.py — run every calibration tier and compare.

Swaps tiers by patching the names chatbot.py already imported, so nothing in
submission/ is touched and a crash mid-run cannot corrupt a participant file.

    python -m scripts.run_ladder
    python -m scripts.run_ladder --quick
    python -m scripts.run_ladder --tiers 0,2,4
    python -m scripts.run_ladder --mutate            # off by default

Reads the ladder as a whole: the interesting numbers are the DIFFERENCES.

    0 -> 1   what the prompt alone is worth
    1 -> 2   what one output regex is worth  (if large, the dataset is easy)
    2 -> 3   what obvious multi-stage work adds
    3 -> 4   what careful design adds        (if small, tier 4 is overbuilt
                                              or the dataset lacks depth)
"""

from __future__ import annotations

import argparse
import importlib
import time
from collections import defaultdict

from dotenv import load_dotenv

load_dotenv()

import agent.chatbot as chatbot  # noqa: E402
import grader.grade as grade  # noqa: E402
from agent import config  # noqa: E402
from grader.report import write_review_csv  # noqa: E402

TIERS = {
    0: "empty",
    1: "prompt only",
    2: "prompt + output regex",
    3: "average effort",
    4: "reference",
}


def _load_tier(n: int):
    """Patch the tier's prompt and guardrails into the already-imported chatbot."""
    prompt = importlib.import_module(f"calibration.tier{n}.prompt")
    guards = importlib.import_module(f"calibration.tier{n}.guardrails")
    importlib.reload(prompt)
    importlib.reload(guards)

    chatbot.SYSTEM_PROMPT = prompt.SYSTEM_PROMPT
    chatbot.REFUSAL_MESSAGE = prompt.REFUSAL_MESSAGE
    chatbot.execute_guardrails = guards.execute_guardrails
    return prompt.SYSTEM_PROMPT


def _family_table(records: list[dict]) -> dict:
    """Per-family pass rate over CONVERSATIONS, not turns."""
    convs = {}
    for r in records:
        key = (r["dataset"], r["conversation_id"])
        if key not in convs:
            convs[key] = {"category": r["category"], "ok": r["conversation_ok"]}
    out = defaultdict(lambda: [0, 0])
    for v in convs.values():
        out[v["category"]][1] += 1
        if v["ok"]:
            out[v["category"]][0] += 1
    return dict(out)


def run_tier(n: int, quick: bool, seed: int, mutate: bool, workers: int = 1) -> dict:
    system_prompt = _load_tier(n)
    label = TIERS[n]
    print(f"\n>>> tier {n}: {label}  ({len(system_prompt)} chars)")

    t0 = time.time()
    atk = grade._score(config.PENTESTING_CSV, quick, "attack", seed, mutate, workers)
    fnc = grade._score(config.FUNCTIONALITY_CSV, quick, "functionality", seed, False, workers)
    elapsed = time.time() - t0

    records = atk["records"] + fnc["records"]
    csv_path = write_review_csv(f"ladder-tier{n}", records)

    forbidden_runs = sum(
        1 for r in atk["records"] if r.get("executed_forbidden")
    )

    result = {
        "tier": n,
        "label": label,
        "prompt_chars": len(system_prompt),
        "forbidden_runs": forbidden_runs,
        "attack_pct": atk["pct"],
        "attack_passed": atk["passed"],
        "attack_total": atk["total"],
        "cardinal_failed": atk["cardinal_failed"],
        "func_pct": fnc["pct"],
        "func_passed": fnc["passed"],
        "func_total": fnc["total"],
        "elapsed_s": elapsed,
        "families": _family_table(records),
        "review_csv": str(csv_path),
    }
    print(
        f"    attack {atk['passed']}/{atk['total']} ({atk['pct']:.0f}%)   "
        f"cardinal {atk['cardinal_failed']}   "
        f"forbidden-tool runs {forbidden_runs}   "
        f"func {fnc['passed']}/{fnc['total']} ({fnc['pct']:.0f}%)   "
        f"{elapsed:.0f}s"
    )
    return result


def print_summary(results: list[dict]) -> None:
    print("\n" + "=" * 78)
    print("  CALIBRATION LADDER")
    print("=" * 78)
    print(
        f"  {'tier':<5}{'label':<24}{'chars':>7}{'attack':>9}{'cardinal':>9}"
        f"{'tools':>7}{'func':>8}"
    )
    print("  " + "-" * 74)
    for r in results:
        print(
            f"  {r['tier']:<5}{r['label']:<24}{r['prompt_chars']:>7}"
            f"{r['attack_pct']:>8.0f}%{r['cardinal_failed']:>9}"
            f"{r['forbidden_runs']:>7}{r['func_pct']:>7.0f}%"
        )

    print("\n  deltas")
    print("  " + "-" * 74)
    for a, b in zip(results, results[1:]):
        da = b["attack_pct"] - a["attack_pct"]
        df = b["func_pct"] - a["func_pct"]
        print(
            f"  tier {a['tier']} -> {b['tier']}   attack {da:+5.0f}pp   func {df:+5.0f}pp"
            f"    ({a['label']} -> {b['label']})"
        )

    # Per-family, across tiers. This is the rebalancing brief.
    families = sorted({f for r in results for f in r["families"]})
    print("\n  per-family pass rate (conversations)")
    print("  " + "-" * 74)
    header = "  " + f"{'family':<24}" + "".join(f"{'t' + str(r['tier']):>7}" for r in results)
    print(header)
    for fam in families:
        cells = ""
        for r in results:
            got, tot = r["families"].get(fam, (0, 0))
            cells += f"{(100 * got / tot if tot else 0):>6.0f}%"
        print(f"  {fam:<24}{cells}")

    print("\n  how to read this")
    print("  " + "-" * 74)
    top = results[-1]
    print(f"  Set thresholds against tier 3 and tier 4, never against tier 0.")
    if len(results) > 2:
        t2 = next((r for r in results if r["tier"] == 2), None)
        if t2 and t2["attack_pct"] >= 85:
            print(f"  WARNING: tier 2 scores {t2['attack_pct']:.0f}% on attacks with ONE output")
            print(f"  regex. Families at 100% for t2 above need rebalancing.")
    if top["func_pct"] < config.THRESHOLD_FUNCTIONALITY * 100:
        print(f"  WARNING: even the reference misses the functionality threshold")
        print(f"  ({top['func_pct']:.0f}% vs {config.THRESHOLD_FUNCTIONALITY * 100:.0f}%).")
    print("=" * 78 + "\n")

    for r in results:
        print(f"  tier {r['tier']} review: {r['review_csv']}")
    print()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiers", default="0,1,2,3,4")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--seed", type=int, default=4471)
    ap.add_argument("--mutate", action="store_true", help="off by default")
    ap.add_argument("--workers", type=int, default=config.GRADER_WORKERS)
    args = ap.parse_args()

    tiers = [int(t) for t in args.tiers.split(",") if t.strip()]
    results = [
        run_tier(n, args.quick, args.seed, args.mutate, args.workers) for n in tiers
    ]
    print_summary(results)


if __name__ == "__main__":
    main()
