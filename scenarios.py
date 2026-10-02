#!/usr/bin/env python3
"""
scenarios.py — 20 synthetic PayPal account scenarios for the hold-detection
evaluation, and the scored harness that runs them.

Why this exists (playbook rule 11 — "prove the rejection"):
> "If you can't quote a failure rate, you've proven nothing."

The reference winner shipped "two thirds rejected" as evidence. We need the
same, honestly measured, BEFORE any demo video.

Critically: these are SYNTHETIC accounts. They are not real people's data, they
are not scraped from PayPal, and they encode the failure modes PayPal publishes
about holds. The point is to measure the ENGINE's discrimination, and to be
explicit about what that does and does not prove (see LIMITATIONS below).

Usage:
    python3 scenarios.py --run          # evaluate, print report + metrics
    python3 scenarios.py --explain bad # why each verdict went the way it did
"""
from __future__ import annotations

import json
import sys
from copy import deepcopy

from hold_signals import diagnose

# ── a neutral account; scenarios mutate a deep copy ─────────────────────────
NEUTRAL = {
    "id": "acct",
    "withheld_balance": 0.0,
    "total_balance": 8000.0,
    "daily_volume_baseline_30d": [40, 42, 38, 45, 41, 43, 39, 44, 40, 42,
                                   41, 43, 39, 45, 41, 40, 42, 44, 39, 43,
                                   41, 42, 40, 45, 41, 43, 39, 44, 40, 42],
    "recent_daily_volume": [41, 42, 40],
    "historical_countries": ["US", "GB", "CA"],
    "recent_countries": ["US", "GB", "CA"],
    "recent_dispute_rate": 0.005,
    "baseline_dispute_rate": 0.006,
    "profile_changes_last_7d": [],
    "historical_payout_destinations": ["acct_a", "acct_b", "acct_c"],
    "recent_payout_destinations": ["acct_a", "acct_b", "acct_c"],
    "refund_rate": 0.02,
    "recent_amounts": [12.37, 88.19, 41.02, 7.55, 33.80, 19.44] * 5,
}


def acct(**kw):
    a = deepcopy(NEUTRAL)
    a.update(kw)
    return a


# ── 20 scenarios. `hold` is GROUND TRUTH, set independently of the engine. ──
SCENARIOS = [
    # ---------- expected HOLD (10) ----------
    ("h01_money_already_held", True,
     acct(withheld_balance=4000.0, total_balance=4500.0),
     "money is already held — the decisive case"),
    ("h02_volume_spike", True,
     acct(recent_daily_volume=[41, 950]),
     "daily volume ~430σ above personal baseline"),
    ("h03_dispute_storm", True,
     acct(recent_dispute_rate=0.14, baseline_dispute_rate=0.01),
     "disputes 14% of transactions, 14x trailing rate"),
    ("h04_identity_rewrite", True,
     acct(profile_changes_last_7d=["name", "address", "bank_account", "phone"]),
     "four identity fields changed in a week"),
    ("h05_new_geography", True,
     acct(recent_countries=["US", "RU", "NG", "PH", "RO"]),
     "60% of activity from countries never seen"),
    ("h06_payout_destination_spray", True,
     acct(recent_payout_destinations=["acct_x", "acct_y", "acct_z",
                                      "acct_w", "acct_v", "acct_u"]),
     "every recent payout is a first-time destination"),
    ("h07_combined_moderate", True,
     acct(recent_daily_volume=[41, 210], recent_dispute_rate=0.07,
          profile_changes_last_7d=["address", "bank_account"],
          recent_countries=["US", "NG"]),
     "no single decisive signal; four moderate ones stack"),
    ("h08_refund_flood", True,
     acct(refund_rate=0.34, recent_dispute_rate=0.05, baseline_dispute_rate=0.005),
     "a third of transactions are refunds"),
    ("h09_structuring", True,
     acct(recent_amounts=[500.00, 1000.00, 500.00, 1000.00,
                          1000.00, 500.00, 1000.00, 500.00,
                          1000.00, 500.00, 1000.00, 500.00]),
     "every amount is round — classic structuring shape"),
    ("h10_held_plus_everything", True,
     acct(withheld_balance=6100.0, total_balance=6200.0,
          recent_daily_volume=[41, 1400], recent_dispute_rate=0.19,
          profile_changes_last_7d=["name", "address", "bank_account"],
          recent_countries=["US", "RU", "IR"]),
     "worst case: held funds plus every other signal"),

    # ---------- expected NO HOLD (10) ----------
    ("n01_clean_steady", False, acct(),
     "a healthy account, no pattern"),
    ("n02_mild_volume_blip", False,
     acct(recent_daily_volume=[41, 58]),
     "1.6σ — inside normal variation for a growing account"),
    ("n03_disputes_elevated_not_spiking", False,
     acct(recent_dispute_rate=0.02, baseline_dispute_rate=0.006),
     "2% disputes, within the absolute cap, ~3x baseline but modest"),
    ("n04_one_profile_change", False,
     acct(profile_changes_last_7d=["phone"]),
     "a single field change is routine"),
    ("n05_return_to_known_country", False,
     acct(recent_countries=["US", "GB", "CA", "DE"]),
     "one country at 25% — just under the 30% trigger"),
    ("n06_round_amounts_organic", False,
     acct(recent_amounts=[10.00, 10.00, 10.00, 25.00, 12.50, 7.50,
                          10.00, 25.00, 40.00, 12.50, 7.50, 10.00]),
     "a florist/grocery — round prices are the business model, not evasion"),
    ("n07_one_new_payout", False,
     acct(recent_payout_destinations=["acct_a", "acct_b", "acct_new", "acct_c"]),
     "1 of 4 new — normal expansion"),
    ("n08_high_refunds_low_value", False,
     acct(refund_rate=0.12, total_balance=90.0),
     "12% refunds but trivial value — not a laundering pattern"),
    ("n09_sparse_history", False,
     acct(daily_volume_baseline_30d=[42, 41, 43], recent_countries=["US"]),
     "too little history to assert anything — must not hallucinate a baseline"),
    ("n10_new_account_everything_looks_new", False,
     acct(daily_volume_baseline_30d=[41, 42], historical_countries=[],
        historical_payout_destinations=[], recent_daily_volume=[40]),
     "a brand-new account: novelty is not evidence of risk"),
]

LIMITATIONS = """
LIMITATIONS — state these in the README, without being asked.
  1. These accounts are SYNTHETIC. Ground truth is ours, not PayPal's.
  2. We measure the ENGINE's discrimination on known failure shapes.
     We have NOT measured whether PayPal actually holds accounts for
     these reasons, or in these proportions.
  3. Real PayPal hold decisions are not public. There is no ground-truth
     dataset available to anyone, including us.
  4. Therefore this number measures OUR rules, not PayPal's behaviour.
     It is evidence the engine is not decorative (playbook rule 10) and
     nothing more.
  5. A production system would be tuned against outcomes we cannot obtain
     in a hackathon window. Say so rather than implying otherwise.
"""


def run(verbose: bool = False) -> dict:
    rows = []
    for name, truth, account, why in SCENARIOS:
        d = diagnose(account)
        rows.append({
            "scenario": name,
            "ground_truth_hold": truth,
            "engine_says": d["verdict"],
            "score": d["risk_score"],
            "rules_fired": [s["rule"] for s in d["signals_fired"]],
            "rationale": why,
        })

    # discrimination metrics
    tp = sum(1 for r in rows if r["ground_truth_hold"] and r["engine_says"] == "HIGH")
    fn = sum(1 for r in rows if r["ground_truth_hold"] and r["engine_says"] != "HIGH")
    fp = sum(1 for r in rows if not r["ground_truth_hold"] and r["engine_says"] == "HIGH")
    tn = sum(1 for r in rows if not r["ground_truth_hold"] and r["engine_says"] != "HIGH")

    recall = tp / (tp + fn) if (tp + fn) else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return {
        "n_scenarios": len(rows),
        "confusion": {"true_positive": tp, "false_negative": fn,
                      "false_positive": fp, "true_negative": tn},
        "recall_on_known_hold_shapes": round(recall, 3),
        "precision_on_known_clean_shapes": round(precision, 3),
        "f1": round(f1, 3),
        "overall_accuracy": round((tp + tn) / len(rows), 3),
        "rows": rows,
        "limitations": LIMITATIONS.strip(),
    }


def main() -> int:
    if "--explain" in sys.argv:
        target = sys.argv[sys.argv.index("--explain") + 1]
        for name, truth, account, why in SCENARIOS:
            if name == target:
                d = diagnose(account)
                print(json.dumps({"scenario": name, "ground_truth_hold": truth,
                                  "rationale": why, "diagnosis": d}, indent=2))
                return 0
        print(f"no scenario named {target}")
        return 2

    rep = run()
    print("=" * 78)
    print("USX → PayPal hold-detection ENGINE — scored on 20 synthetic scenarios")
    print("=" * 78)
    print(f"{'scenario':34s} {'truth':>7s} {'engine':>8s} {'score':>6s}  rules fired")
    print("-" * 78)
    for r in rep["rows"]:
        t = "HOLD" if r["ground_truth_hold"] else "clean"
        print(f"{r['scenario']:34s} {t:>7s} {r['engine_says']:>8s} {r['score']:>6d}  "
              f"{', '.join(r['rules_fired'][:3])}")

    c = rep["confusion"]
    print("-" * 78)
    print(f"  scenarios           : {rep['n_scenarios']}")
    print(f"  true positive       : {c['true_positive']}   false negative: {c['false_negative']}")
    print(f"  false positive      : {c['false_positive']}   true negative : {c['true_negative']}")
    print(f"  recall (hold shapes): {rep['recall_on_known_hold_shapes']}")
    print(f"  precision (clean)   : {rep['precision_on_known_clean_shapes']}")
    print(f"  F1                  : {rep['f1']}")
    print(f"  accuracy            : {rep['overall_accuracy']}")
    print("\n" + rep["limitations"])
    with open("/root/web3alphatester/paypal/eval_report.json", "w") as f:
        json.dump(rep, f, indent=2)
    print("\n  full report -> paypal/eval_report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
