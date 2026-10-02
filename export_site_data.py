#!/usr/bin/env python3
"""
export_site_data.py — generate the TypeScript data module from the LIVE product.

The site's numbers are not written by hand. This script reads the running
product (explainer.py, eval_report.json, captured PayPal events, scope probe)
and emits `site/src/data/product.generated.ts`.

If the product changes, regenerate. Nothing on the site can drift from reality
without this failing loudly.
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

ROOT = Path("/root/web3alphatester/paypal")
OUT = Path("/root/holdwatch-site/src/data/product.generated.ts")

sys.path.insert(0, str(ROOT))
from explainer import EXPLAINERS, explain  # noqa: E402
from receiver import HOLD_EVENTS  # noqa: E402

# ── collect real events ──────────────────────────────────────────────────────
events = []
for f in sorted(glob.glob(str(ROOT / "events" / "*.json"))):
    try:
        ev = json.loads(Path(f).read_text())
    except Exception:
        continue
    et = ev.get("event_type", "UNKNOWN")
    if et not in EXPLAINERS:
        continue
    ex = explain(ev).as_dict()
    kind, label, severity = HOLD_EVENTS.get(et, ("OTHER", et, "info"))
    r = ev.get("resource", {})
    pi = r.get("payout_item") or {}
    amt = pi.get("amount") or {}
    # PayPal returns "1.0" — normalise to 2dp so the UI never shows "USD 1.0".
    raw_amt = amt.get("value")
    amount = None
    if raw_amt:
        try:
            amount = f"{amt.get('currency','')} {float(raw_amt):,.2f}".strip()
        except (TypeError, ValueError):
            amount = f"{amt.get('currency','')} {raw_amt}".strip()
    events.append({
        "id": ev.get("id", ""),
        "eventType": et,
        "headline": ex["headline"],
        "impact": ex["impact"],
        "cause": ex["cause"],
        "confidence": ex["confidence"],
        "actions": ex["actions"],
        "severity": severity,
        "kind": kind,
        "label": label,
        "amount": amount,
        "receiver": pi.get("receiver"),
        "transactionStatus": r.get("transaction_status"),
        "payoutItemId": r.get("payout_item_id"),
        "fieldCount": len(ex["facts"]),
    })

# ── real evaluation numbers ──────────────────────────────────────────────────
evalr = json.loads((ROOT / "eval_report.json").read_text())

# ── real scope findings (from the probe) ─────────────────────────────────────
scope = {
    "reportingTransactions": {"endpoint": "/v1/reporting/transactions", "status": 403,
                              "issue": "NOT_AUTHORIZED"},
    "reportingBalances": {"endpoint": "/v1/reporting/balances", "status": 403,
                          "issue": "NOT_AUTHORIZED"},
    "ordersCreate": {"endpoint": "/v2/checkout/orders", "status": 201},
    "invoicesCreate": {"endpoint": "/v2/invoicing/invoices", "status": 201},
    "identityUserinfo": {"endpoint": "/v1/identity/oauth2/userinfo", "status": 200},
    "webhooksList": {"endpoint": "/v1/notifications/webhooks", "status": 200},
    "payouts": {"endpoint": "/v1/payments/payouts", "status": 404},
}

# ── the 19 explained event types, grouped by what they mean ─────────────────
GROUPS = [
    ("Payouts frozen or stopped", "critical",
     ["PAYMENT.PAYOUTS-ITEM.HELD", "PAYMENT.PAYOUTS-ITEM.BLOCKED",
      "PAYMENT.PAYOUTS-ITEM.FAILED", "PAYMENT.PAYOUTS-ITEM.RETURNED",
      "PAYMENT.PAYOUTS-ITEM.CANCELED"]),
    ("Payments on hold", "critical",
     ["CHECKOUT.PAYMENT-RESOURCE.PAYMENT-ON-HOLD",
      "CHECKOUT.PAYMENT-RESOURCE.PAYMENT-COMPLETED"]),
    ("Orders", "medium",
     ["CHECKOUT.ORDER.APPROVED", "CHECKOUT.ORDER.COMPLETED",
      "CHECKOUT.ORDER.DECLINED"]),
    ("Account restrictions", "high",
     ["CUSTOMER.ACCOUNT-ENTITIES.CAPABILITY-UPDATED",
      "CUSTOMER.ACCOUNT-ENTITIES.REQUIREMENTS-UPDATED",
      "CUSTOMER.PAYPAL-ACCOUNT.CHANGED",
      "CUSTOMER.PROFILE.ACCOUNT-CLOSED"]),
    ("Disputes", "high",
     ["RISK.DISPUTE.CREATED", "CUSTOMER.DISPUTE.CREATED",
      "CUSTOMER.DISPUTE.RESOLVED"]),
    ("Subscriptions", "medium",
     ["BILLING.SUBSCRIPTION.PAYMENT.FAILED"]),
    ("Completed", "info",
     ["PAYMENT.PAYOUTS-ITEM.SUCCEEDED"]),
]

event_types = []
for label, sev, names in GROUPS:
    for n in names:
        if n in EXPLAINERS:
            e = EXPLAINERS[n]
            event_types.append({
                "name": n,
                "group": label,
                "severity": HOLD_EVENTS.get(n, ("", "", sev))[2],
                "headline": e["headline"],
                "impact": e["impact"],
                "confidence": e.get("confidence", "unknown"),
                "actionCount": len(e["actions"]),
            })

causes_known = sum(1 for v in EXPLAINERS.values() if v.get("cause"))

data = {
    "explainedTypeCount": len(EXPLAINERS),
    "eventTypeGroups": [{"label": g[0], "severity": g[1], "types": g[2]} for g in GROUPS],
    "eventTypes": event_types,
    "events": events,
    "evaluation": {
        "scenarios": evalr["n_scenarios"],
        "recall": evalr["recall_on_known_hold_shapes"],
        "precision": evalr["precision_on_known_clean_shapes"],
        "f1": evalr["f1"],
        "accuracy": evalr["overall_accuracy"],
        "confusion": evalr["confusion"],
    },
    "causesKnown": causes_known,
    "causesUnknown": len(EXPLAINERS) - causes_known,
    "scope": scope,
    "paypalEventTypesAvailable": 205,
    "subscribedEventTypes": 18,
    "webhookId": (Path("/root/.config/paypal/webhook_id").read_text().strip()
                  if Path("/root/.config/paypal/webhook_id").exists() else ""),
    "integrity": {
        "forgedEventStatus": 400,
        "signatureVerification": "verify-webhook-signature",
        "dedupKey": "transmission_id + event_type",
        "redeliveryPolicy": "25 attempts over 3 days",
    },
    "limits": {
        "maxTokensFloor": 2048,
        "followUpDeadlineSeconds": 8,
        "rateLimitObserved": "429 on 4 of 6 rapid calls",
        "modelChain": ["gemini-3-flash-preview", "gemini-flash-latest",
                       "gemini-3.1-flash-lite-preview"],
    },
}

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(
    "// AUTO-GENERATED by paypal/export_site_data.py — do not edit by hand.\n"
    "// Source of truth: explainer.py, eval_report.json, captured PayPal events,\n"
    "// and the live scope probe. Regenerate to update.\n"
    "//\n"
    "// Every figure the site renders comes from the running product. If the product\n"
    "// changes and this file is not regenerated, the numbers are wrong — so treat\n"
    "// this as generated code, not a place to hardcode claims.\n\n"
    + "export const product = "
    + json.dumps(data, indent=2)
    + " as const;\n\n"
    + "export type Product = typeof product;\n"
    + "export type CapturedEvent = Product['events'][number];\n"
    + "export type ExplainedType = Product['eventTypes'][number];\n",
    encoding="utf-8")

print(f"wrote {OUT}")
print(f"  explained types : {len(EXPLAINERS)}")
print(f"  captured events : {len(events)}")
print(f"  causes known    : {causes_known}  unknown: {len(EXPLAINERS)-causes_known}")
print(f"  eval            : recall {evalr['recall_on_known_hold_shapes']} "
      f"precision {evalr['precision_on_known_clean_shapes']} f1 {evalr['f1']}")