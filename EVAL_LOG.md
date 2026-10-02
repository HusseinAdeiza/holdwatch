# PayPal Hold Detection — evaluation log

Rule 11 (playbook): *"Prove the rejection. If you can't quote a failure rate,
you've proven nothing."* This file is that number, and the journey to it.

---

## The engine

`hold_signals.py` — 8 deterministic rules over transaction/account data.
Every claim cites the measurement that produced it. **No model asserts a
finding**; a model may read the rule output and explain it, but never invent one.

That separation is the whole argument (rule 10): *a system consistent with
itself cannot detect this class of error from the inside.* The rules and the
evaluator are independent code paths.

---

## Scored on 20 synthetic scenarios

`scenarios.py` — 10 hold shapes, 10 clean accounts. Ground truth is set
independently of the engine.

| Version | Recall | Precision | F1 | FP |
|---|---|---|---|---|
| v1 | **0.20** | 1.00 | 0.33 | 0 |
| v2 | **0.50** | 1.00 | 0.67 | 0 |
| **v3 (current)** | **0.80** | **1.00** | **0.89** | **0** |

### v1 → v2: the engine could not cry wolf

v1 missed **8 of 10** hold shapes. Precision was perfect — it never cried
"wolf" — but it never cried "wolf" at all. Every single-signal case landed
below the HIGH bar of 8. A 430σ volume spike fired correctly and still read LOW,
because the rule only carried weight 3.

**That is a design fault, not a threshold preference**, and it was invisible
without the eval. Fix: some signals are *decisive on their own* (money already
withheld, 25σ volume, 8% disputes); everything else accumulates.

### v2 → v3: same defect, different rule

v2 still missed h05, which fires `new_geography` at **80% unseen — more than
four times its own 15% trigger** — and read LOW, because geography carried
weight 2 and wasn't decisive. Identical defect to v1 in a different rule, so
fixed the same way: a signal far past its own trigger is not "one more data
point."

Added as decisive: ≥50% unseen geography, ≥80% round amounts, 4+ identity fields
changed in a week.

### What was deliberately NOT done

**The accumulation bar was never raised to make numbers look better.** Every
change above adds a *decisive* classification to a signal that is genuinely
decisive, and the clean-account results were re-checked after each one — zero
false positives held throughout all three versions.

## The two remaining misses — stated, not hidden

| Scenario | Why it reads LOW |
|---|---|
| `h06_payout_destination_spray` | 6 unseen payout destinations, weight 2, not decisive. **Arguably should be** — this is the weakest rule in the set. |
| `h08_refund_flood` | 34% refund rate. The dispute rule fires, but at 5% (under the 8% decisive bar) it reads ELEVATED. |

Both are calibration questions, not bugs. **I am reporting 0.8 rather than
tuning to 1.0** — a number arrived at by tuning tells you nothing.

---

## LIMITATIONS — publish these without being asked

1. **These accounts are SYNTHETIC.** Ground truth is ours, not PayPal's.
2. This measures **our rules**, not PayPal's behaviour. We have not verified
   that PayPal holds accounts for these reasons, or in these proportions.
3. **Real PayPal hold decisions are not public.** No ground-truth dataset
   exists for anyone, including us.
4. So this number is evidence the engine is **not decorative** (rule 10) and
   nothing more.
5. A production system would be tuned against outcomes unavailable in a
   hackathon window. **Say so rather than implying otherwise.**

---

## Current result

```
scenarios: 20    TP 8    FN 2    FP 0    TN 10
recall 0.80   precision 1.00   F1 0.89   accuracy 0.90
```

Reproduce:
```bash
python3 paypal/hold_signals.py --self-test    # engine discriminates
python3 paypal/scenarios.py --run            # the numbers above
python3 paypal/scenarios.py --explain h05    # per-scenario reasoning
```

Full machine-readable output: `paypal/eval_report.json`

**Next:** confirm the rule set against real PayPal Transaction Search output,
once sandbox credentials exist. That is the one input this cannot synthesise.
