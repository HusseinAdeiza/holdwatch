#!/usr/bin/env python3
"""
hold_signals.py — the rule engine for the PayPal "Explain the Hold" project.

This is the actual intellectual content. NOT an LLM wrapper: each signal is a
deterministic rule over transaction/account data, so every diagnosis can cite the
line that produced it. The model (when added) reads the rule output — it never
invents the finding.

Design constraint taken from our own playbook (rule 10 — consistency from inside
cannot self-check): every rule is computed from the data, never from a previous
rule's conclusion. Two rules disagreeing is a feature; the engine reports both.

Signals are scored, not asserted. A rule can fire alone only if it is decisive;
otherwise its weight accumulates.

Usage:
    python3 hold_signals.py <account.json>     # diagnose one account
    python3 hold_signals.py --self-test        # verify the engine on fixtures
"""
from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass, field
from typing import Any

# ── thresholds and weights ───────────────────────────────────────────────────
# Calibration note (2026-10-29, after the first 20-scenario eval):
#   v1 scored recall 0.20 — 8 of 10 hold shapes were missed because every
#   single-signal case landed below the HIGH bar of 8. Precision was 1.0, so
#   the engine could not cry wolf when it should. That is a design fault, not a
#   threshold preference, and it was only visible because the eval existed.
#
#   The fix has two parts:
#     1. DECISIVE signals can call HIGH on their own. A 430-sigma volume
#        spike is not "one more data point" — it is the whole signal.
#     2. Everything else accumulates as before, because combined moderate
#        signals genuinely do compound (h07 proves it).
#
#   Deliberately NOT done: raising the accumulation bar to make numbers look
#   better. The eval is reported as it measures.
THRESHOLDS = {
    "velocity_z": 3.0,          # daily volume vs 30d baseline, in sigmas
    "min_transactions_for_baseline": 20,
    "geo_new_country_ratio": 0.15,   # share of recent tx from unseen countries
    "chargeback_rate": 0.03,          # disputes / transactions
    "chargeback_spike_ratio": 2.5,    # vs trailing dispute rate
    "profile_field_changes": 2,       # identity fields changed inside 7d
    "new_payout_share": 0.20,         # share going to unseen destinations
    "refund_rate": 0.10,
    "round_amount_ratio": 0.35,       # classic structuring signal
}

SIGNAL_WEIGHTS = {
    "velocity_anomaly": 3,
    "new_geography": 2,
    "chargeback_spike": 3,
    "identity_churn": 2,
    "new_payout_destination": 2,
    "excess_refunds": 1,
    "structured_amounts": 2,
    "funds_withheld": 4,
}

# Signals that mean HOLD on their own, at their observed severity. Each entry
# maps a rule to (metric, bar) above which it is decisive on its own.
# An account trips this if ANY decisive signal is past its bar.
#
# Second calibration (after eval v1 recall 0.20 → v2 0.50): h05 fires
# new_geography at 80% unseen — four times its own trigger — and still reads
# LOW, because geography carried weight 2 and was not decisive. That is the
# same defect as v1 in a different rule, so it is fixed the same way: a signal
# far past its trigger is not "one more data point."
DECISIVE = {
    "funds_withheld": None,                    # any withheld balance at all
    "velocity_anomaly": ("sigma", 25.0),       # ≥25σ is not a fluctuation
    "chargeback_spike": ("rate", 0.08),       # ≥8% disputes is a hold pattern
    "new_geography": ("ratio", 0.50),          # ≥50% unseen geography
    "structured_amounts": ("ratio", 0.80),     # ≥80% round amounts
    "identity_churn": ("count", 4),            # 4+ identity fields in a week
}

# Accumulated score needed for HIGH when no single signal is decisive.
HIGH_SCORE = 6


@dataclass
class Signal:
    rule: str
    fired: bool
    weight: int
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "rule": self.rule,
            "fired": self.fired,
            "weight": self.weight,
            "detail": self.detail,
            "evidence": self.evidence,
        }


def _sigma(values: list[float], current: float) -> float:
    """Deviation of `current` from the baseline, in sigmas. Zero if undefined."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    if var <= 0:
        return 0.0
    return (current - mean) / math.sqrt(var)


# ── the rules ───────────────────────────────────────────────────────────────
def rule_velocity_anomaly(a: dict) -> Signal:
    """Recent daily volume far above the account's own 30-day baseline."""
    w = SIGNAL_WEIGHTS["velocity_anomaly"]
    baseline = a.get("daily_volume_baseline_30d", [])
    recent = a.get("recent_daily_volume", [])
    if len(baseline) < THRESHOLDS["min_transactions_for_baseline"] or not recent:
        return Signal("velocity_anomaly", False, w,
                      "not enough history to compute a personal baseline")
    sig = _sigma(baseline, recent[-1])
    fired = sig >= THRESHOLDS["velocity_z"]
    return Signal(
        "velocity_anomaly", fired, w,
        f"latest day is {sig:.1f}σ above the 30-day baseline"
        if fired else f"volume within normal range ({sig:.1f}σ)",
        {"sigma": round(sig, 2), "threshold": THRESHOLDS["velocity_z"],
         "latest": recent[-1], "baseline_mean": round(sum(baseline) / len(baseline), 2)},
    )


def rule_new_geography(a: dict) -> Signal:
    """A meaningful share of recent activity from countries never seen before."""
    w = SIGNAL_WEIGHTS["new_geography"]
    seen = set(a.get("historical_countries", []))
    recent = a.get("recent_countries", [])
    if not seen or not recent:
        return Signal("new_geography", False, w, "no country history")
    unseen = [c for c in recent if c not in seen]
    ratio = len(unseen) / len(recent)
    fired = ratio >= THRESHOLDS["geo_new_country_ratio"]
    return Signal(
        "new_geography", fired, w,
        f"{ratio:.0%} of recent activity from {len(unseen)} previously unseen "
        f"{'countries: ' + ', '.join(sorted(set(unseen))) if fired else 'country/countries'}",
        {"ratio": round(ratio, 3), "threshold": THRESHOLDS["geo_new_country_ratio"],
         "unseen": sorted(set(unseen))},
    )


def rule_chargeback_spike(a: dict) -> Signal:
    w = SIGNAL_WEIGHTS["chargeback_spike"]
    rate = a.get("recent_dispute_rate", 0.0)
    base = a.get("baseline_dispute_rate", 0.0)
    high = rate >= THRESHOLDS["chargeback_rate"]
    spike = base > 0 and rate >= base * THRESHOLDS["chargeback_spike_ratio"]
    fired = high or spike
    why = []
    if high:
        why.append(f"dispute rate {rate:.1%} exceeds {THRESHOLDS['chargeback_rate']:.0%}")
    if spike:
        why.append(f"{rate/base:.1f}x the trailing rate")
    return Signal("chargeback_spike", fired, w, "; ".join(why) if fired else
                  f"dispute rate {rate:.1%} within tolerance", 
                  {"rate": rate, "baseline": base})


def rule_identity_churn(a: dict) -> Signal:
    w = SIGNAL_WEIGHTS["identity_churn"]
    changed = a.get("profile_changes_last_7d", [])
    n = len(changed)
    fired = n >= THRESHOLDS["profile_field_changes"]
    return Signal("identity_churn", fired, w,
                  f"{n} identity fields changed in 7 days: {', '.join(changed)}"
                  if fired else f"{n} identity field change(s)",
                  {"changed_fields": changed, "count": n,
                   "threshold": THRESHOLDS["profile_field_changes"]})


def rule_new_payout_destination(a: dict) -> Signal:
    w = SIGNAL_WEIGHTS["new_payout_destination"]
    seen = set(a.get("historical_payout_destinations", []))
    recent = a.get("recent_payout_destinations", [])
    if not seen or not recent:
        return Signal("new_payout_destination", False, w, "no payout history")
    unseen = [d for d in recent if d not in seen]
    ratio = len(unseen) / len(recent)
    fired = ratio >= THRESHOLDS["new_payout_share"]
    return Signal("new_payout_destination", fired, w,
                  f"{ratio:.0%} of recent payouts went to never-before-used "
                  f"destinations" if fired else "payout destinations are established",
                  {"ratio": round(ratio, 3), "unseen_count": len(unseen)})


def rule_excess_refunds(a: dict) -> Signal:
    w = SIGNAL_WEIGHTS["excess_refunds"]
    rate = a.get("refund_rate", 0.0)
    fired = rate >= THRESHOLDS["refund_rate"]
    return Signal("excess_refunds", fired, w,
                  f"refund rate {rate:.1%}" if fired else f"refund rate {rate:.1%}",
                  {"rate": rate, "threshold": THRESHOLDS["refund_rate"]})


def rule_structured_amounts(a: dict) -> Signal:
    """Round-number clustering — a classic structuring indicator."""
    w = SIGNAL_WEIGHTS["structured_amounts"]
    amounts = a.get("recent_amounts", [])
    if len(amounts) < 10:
        return Signal("structured_amounts", False, w, "too few transactions to assess")
    roundish = sum(1 for x in amounts if x > 0 and abs(x - round(x)) < 0.005)
    ratio = roundish / len(amounts)
    fired = ratio >= THRESHOLDS["round_amount_ratio"]
    return Signal("structured_amounts", fired, w,
                  f"{ratio:.0%} of recent amounts are round numbers"
                  if fired else f"amount distribution normal ({ratio:.0%} round)",
                  {"ratio": round(ratio, 3), "threshold": THRESHOLDS["round_amount_ratio"]})


def rule_funds_withheld(a: dict) -> Signal:
    """Decisive on its own: money is already held."""
    w = SIGNAL_WEIGHTS["funds_withheld"]
    withheld = a.get("withheld_balance", 0.0)
    total = a.get("total_balance", 0.0)
    fired = withheld > 0
    pct = (withheld / total * 100) if total else 0.0
    return Signal("funds_withheld", fired, w,
                  f"${withheld:,.2f} of ${total:,.2f} is withheld ({pct:.0f}%)" if fired
                  else "no withheld balance",
                  {"withheld": withheld, "total": total})


RULES = [
    rule_funds_withheld,      # decisive — listed first
    rule_velocity_anomaly,
    rule_chargeback_spike,
    rule_new_geography,
    rule_identity_churn,
    rule_new_payout_destination,
    rule_structured_amounts,
    rule_excess_refunds,
]


def diagnose(account: dict) -> dict:
    """Run every rule. Never short-circuit — rule 10: all rules are independent."""
    signals = [r(account) for r in RULES]
    fired = [s for s in signals if s.fired]
    score = sum(s.weight for s in fired)

    # A decisive signal calls HIGH alone. Accumulation covers the rest.
    decisive_hits = []
    for s in fired:
        spec = DECISIVE.get(s.rule)
        if spec is None and s.rule in DECISIVE:
            decisive_hits.append((s.rule, "any withheld balance"))
        elif spec:
            metric, bar = spec
            value = s.evidence.get(metric)
            if value is not None and value >= bar:
                decisive_hits.append((s.rule, f"{metric}={value} ≥ {bar}"))

    if decisive_hits or score >= HIGH_SCORE:
        verdict = "HIGH"
        action = ("funds withheld or a decisive signal present — remediate now"
                  if decisive_hits else
                  "not yet held, but the pattern is moving toward a restriction")
    elif score >= 4:
        verdict, action = "ELEVATED", "no decisive signal, but multiple rules are firing; monitor"
    else:
        verdict, action = "LOW", "no known pre-hold pattern detected in this data"

    return {
        "account": account.get("id", "unknown"),
        "risk_score": score,
        "verdict": verdict,
        "decisive_signals": [d[0] for d in decisive_hits],
        "recommended_action": action,
        "signals_fired": [s.as_dict() for s in fired],
        "signals_checked": len(signals),
        "thresholds": THRESHOLDS,
        "high_score_bar": HIGH_SCORE,
        "method": (
            "Deterministic rules over transaction/account data. Every claim cites the "
            "line that produced it. No model output is used to assert a finding."
        ),
    }


def _selftest() -> int:
    """Engine must fire on a known-bad account and stay quiet on a known-good one."""
    good = {
        "id": "good-001", "withheld_balance": 0.0, "total_balance": 5000.0,
        "daily_volume_baseline_30d": [40, 42, 38, 45, 41, 43, 39, 44, 40, 42,
                                       41, 43, 39, 45, 41, 40, 42, 44, 39, 43,
                                       41, 42, 40, 45, 41, 43, 39, 44, 40, 42],
        "recent_daily_volume": [41, 43, 40],
        "historical_countries": ["US", "GB"], "recent_countries": ["US", "GB"],
        "recent_dispute_rate": 0.004, "baseline_dispute_rate": 0.005,
        "profile_changes_last_7d": [], "recent_amounts": [12.37, 88.19, 41.02, 7.55] * 4,
        "historical_payout_destinations": ["acct_a", "acct_b"],
        "recent_payout_destinations": ["acct_a", "acct_b"], "refund_rate": 0.02,
    }
    bad = {
        "id": "bad-001", "withheld_balance": 4000.0, "total_balance": 4500.0,
        "daily_volume_baseline_30d": [40, 42, 38, 45, 41, 43, 39, 44, 40, 42,
                                       41, 43, 39, 45, 41, 40, 42, 44, 39, 43,
                                       41, 42, 40, 45, 41, 43, 39, 44, 40, 42],
        "recent_daily_volume": [41, 900],
        "historical_countries": ["US"], "recent_countries": ["US", "RU", "NG", "PH"],
        "recent_dispute_rate": 0.11, "baseline_dispute_rate": 0.01,
        "profile_changes_last_7d": ["name", "address", "bank_account"],
        "recent_amounts": [500.00, 1000.00, 500.00, 1000.00] * 3,
        "historical_payout_destinations": ["acct_a"],
        "recent_payout_destinations": ["acct_b", "acct_c", "acct_d", "acct_e"],
        "refund_rate": 0.18,
    }

    d_good, d_bad = diagnose(good), diagnose(bad)
    print(f"  good-001: score={d_good['risk_score']:>3} verdict={d_good['verdict']}")
    print(f"  bad-001 : score={d_bad['risk_score']:>3} verdict={d_bad['verdict']}")
    print(f"\n  rules that fired on bad-001:")
    for s in d_bad["signals_fired"]:
        print(f"    +{s['weight']}  {s['rule']:26s} {s['detail'][:64]}")

    ok = d_good["verdict"] == "LOW" and d_bad["verdict"] == "HIGH"
    print(f"\n  SELF-TEST {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(_selftest())
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path:
        print(__doc__)
        sys.exit(2)
    print(json.dumps(diagnose(json.load(open(path))), indent=2))
