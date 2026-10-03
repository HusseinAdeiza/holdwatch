#!/usr/bin/env python3
"""
explainer.py — the product's core logic.

Given a PayPal webhook event, produce a plain-language explanation:
  what happened  ->  why it happened  ->  what to do about it

Design rule (playbook A4 / rule 11): every explanation is derived from the
event payload, and each field is traceable to the JSON that produced it. Where
we do not actually know the cause, we say so rather than inventing a confident
reason. A tool that makes things up is worse than one that admits ignorance.

The distinction matters commercially: "PayPal held this payout" is a fact we can
state. "PayPal held it because your account looked fraudulent" is a guess. The
first is useful; the second is a liability.

Each EXPLAINERS entry carries:
  cause      - what is KNOWN about why, or None when genuinely unknown
  confidence - "confirmed" | "likely" | "unknown"
  actions    - concrete next steps, most important first
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Explanation:
    event_type: str
    headline: str
    impact: str
    cause: str | None
    confidence: str
    actions: list[str]
    facts: dict[str, Any] = field(default_factory=dict)
    # Severity and signature-verification status are NOT properties of the
    # explanation — they come from the event envelope. They are carried here so
    # the UI and the API can render one object without a second lookup.
    severity: str = "info"
    verified: bool | None = None
    event_id: str | None = None

    def as_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "event_id": self.event_id,
            "headline": self.headline,
            "impact": self.impact,
            "cause": self.cause,
            "confidence": self.confidence,
            "actions": self.actions,
            "facts": self.facts,
            "severity": self.severity,
            "verified": self.verified,
        }


# Common actions, worded as instructions rather than reassurance.
A_RESOLVE = "Open a PayPal resolution centre case to appeal, if you believe this is a mistake: paypal.com/resolutioncenter"
A_WAIT = "No action needed — this event is informational. Your money was not affected."
A_CHECK_EMAIL = "Check the email PayPal sent for this event; it carries the same case reference"
A_DOCS = "Have delivery/proof-of-delivery documentation ready — it is what resolution cases turn on"

# ── per-event explanations ───────────────────────────────────────────────────
# cause=None means: we observe the event, but PayPal does not disclose the
# underlying reason through this payload. We say so rather than guessing.
EXPLAINERS: dict[str, dict] = {
    "PAYMENT.PAYOUTS-ITEM.HELD": {
        # "a payout you were sending" was flagged as semantically confusing:
        # "payout" usually reads as money coming IN, so pairing it with "you were
        # sending" muddles the direction. "outbound payout" is unambiguous.
        "headline": "PayPal held money you were sending out",
        "impact": "The money has left neither your balance nor the recipient. "
                  "It is frozen pending review.",
        "cause": None,
        "confidence": "unknown",
        "actions": [
            A_RESOLVE,
            "Do not resend the payout — a duplicate would be a second, unrecoverable transfer",
            A_CHECK_EMAIL,
            A_DOCS,
        ],
    },
    "PAYMENT.PAYOUTS-ITEM.BLOCKED": {
        "headline": "PayPal blocked a payout before sending it",
        "impact": "The money did not move. It remains in your balance but cannot "
                  "be paid out to this recipient.",
        "cause": None,
        "confidence": "unknown",
        "actions": [
            "Confirm the recipient's email is correct and belongs to you or an authorised account",
            "Check for a notification email stating which check the payout failed",
            A_RESOLVE,
        ],
    },
    "PAYMENT.PAYOUTS-ITEM.FAILED": {
        "headline": "A payout failed",
        "impact": "The transfer did not complete. Funds were returned to your balance.",
        "cause": None,
        "confidence": "unknown",
        "actions": [A_CHECK_EMAIL, "Retry with a different payout method (bank or card) rather than repeating the same one"],
    },
    "PAYMENT.PAYOUTS-ITEM.RETURNED": {
        "headline": "An unclaimed payout was returned",
        "impact": "The recipient did not claim the money in time; it is back in your balance.",
        "cause": "The recipient did not accept the payout within PayPal's claim window.",
        "confidence": "confirmed",
        "actions": [
            "Confirm the recipient's account is active and able to receive payouts",
            "Resend only after confirming with them — repeated returns can restrict payouts",
        ],
    },
    "PAYMENT.PAYOUTS-ITEM.CANCELED": {
        "headline": "A payout was cancelled",
        "impact": "The transfer was stopped before completion. Funds returned to your balance.",
        "cause": None, "confidence": "unknown",
        "actions": [A_CHECK_EMAIL, "If you did not cancel it, treat this as a security signal and review your account activity"],
    },
    "PAYMENT.PAYOUTS-ITEM.SUCCEEDED": {
        "headline": "A payout completed",
        "impact": "The money reached the recipient.",
        "cause": None, "confidence": "confirmed",
        "actions": [A_WAIT],
    },
    "CHECKOUT.PAYMENT-RESOURCE.PAYMENT-ON-HOLD": {
        "headline": "A payment you received is on hold",
        "impact": "The funds are not yet available to you. PayPal is holding the "
                  "payment pending its own review.",
        "cause": None,
        "confidence": "unknown",
        "actions": [
            "Ship the order as promised — fulfilment is the main thing that releases a hold",
            "Respond fast if the buyer contacted you; unresponsive sellers are the common trigger",
            A_RESOLVE,
        ],
    },
    "CHECKOUT.PAYMENT-RESOURCE.PAYMENT-COMPLETED": {
        "headline": "A payment completed",
        "impact": "The payment is complete and the funds are yours, subject to any hold period.",
        "cause": None, "confidence": "confirmed", "actions": [A_WAIT],
    },
    "CHECKOUT.ORDER.APPROVED": {
        "headline": "A buyer approved your order",
        "impact": "Payment was authorised. Capture it to receive the funds.",
        "cause": None, "confidence": "confirmed",
        "actions": ["Capture the order to take payment — approval expires if you do not"],
    },
    "CHECKOUT.ORDER.COMPLETED": {
        "headline": "An order completed",
        "impact": "Payment captured successfully.",
        "cause": None, "confidence": "confirmed", "actions": [A_WAIT],
    },
    "CHECKOUT.ORDER.DECLINED": {
        "headline": "An order was declined",
        "impact": "The buyer's payment did not complete. They were not charged.",
        "cause": None, "confidence": "unknown",
        "actions": [
            "Do not ship — no payment was taken",
            "Let the buyer retry with another funding source; declines are usually issuer-side",
        ],
    },
    "CUSTOMER.ACCOUNT-ENTITIES.CAPABILITY-UPDATED": {
        "headline": "A capability on your account changed",
        "impact": "PayPal added or removed a permission — commonly a payout method, "
                  "a product, or card acceptance.",
        "cause": None, "confidence": "unknown",
        "actions": [
            A_CHECK_EMAIL,
            "If you lost a capability you need, appeal in the resolution centre",
            "Check this account's status page for any restrictions",
        ],
    },
    "CUSTOMER.ACCOUNT-ENTITIES.REQUIREMENTS-UPDATED": {
        "headline": "PayPal added a requirement to your account",
        "impact": "You are now asked for information — typically identity, business, "
                  "or tax documents. This is usually the precursor to a restriction.",
        "cause": None, "confidence": "unknown",
        "actions": [
            "Submit the requested documents promptly — unmet requirements block payouts",
            "Upload only what was asked for, via paypal.com, not by email",
            A_RESOLVE,
        ],
    },
    "CUSTOMER.PAYPAL-ACCOUNT.CHANGED": {
        "headline": "Your PayPal account details changed",
        "impact": "Something on the account was modified.",
        "cause": None, "confidence": "unknown",
        "actions": [
            "If you did not make this change, secure the account immediately — change the password and review active sessions",
            "Review recent account activity for anything unfamiliar",
        ],
    },
    "CUSTOMER.PROFILE.ACCOUNT-CLOSED": {
        "headline": "Your PayPal account was closed",
        "impact": "The account is closed. Access is limited and payouts stop.",
        "cause": None, "confidence": "unknown",
        "actions": [A_RESOLVE, "Download transaction records before access is removed"],
    },
    "RISK.DISPUTE.CREATED": {
        "headline": "A risk dispute was opened on your account",
        "impact": "PayPal's risk system is reviewing activity associated with your account.",
        "cause": None, "confidence": "unknown",
        "actions": [A_CHECK_EMAIL, A_RESOLVE, "Pause non-essential payouts while the review runs"],
    },
    "CUSTOMER.DISPUTE.CREATED": {
        "headline": "A buyer opened a dispute",
        "impact": "Funds for that transaction are held until the dispute is resolved. "
                  "You have a deadline to submit evidence.",
        "cause": None, "confidence": "confirmed",
        "actions": [
            "Submit evidence before the stated deadline — missing it loses the case automatically",
            A_DOCS,
            "Keep the buyer-facing message factual and short; a long defensive message tends to work against sellers",
        ],
    },
    "CUSTOMER.DISPUTE.RESOLVED": {
        "headline": "A dispute was resolved",
        "impact": "PayPal issued a decision on the dispute.",
        "cause": None, "confidence": "confirmed",
        "actions": [A_CHECK_EMAIL, "If you lost, the decision usually explains what evidence was missing — use that on the next claim"],
    },
    "BILLING.SUBSCRIPTION.PAYMENT.FAILED": {
        "headline": "A subscription payment failed",
        "impact": "The renewal did not complete. The subscription may be suspended.",
        "cause": None, "confidence": "unknown",
        "actions": [
            "Check whether the subscription was suspended and inform the customer directly",
            "Card expiries and insufficient funds are the usual causes",
        ],
    },
}


def _fmt_money(v: Any, currency: str = "") -> str:
    if v is None:
        return ""
    try:
        return f"{currency} {float(v):,.2f}".strip()
    except (TypeError, ValueError):
        return str(v)


def extract_facts(resource: dict) -> dict:
    """
    Pull the handful of fields a merchant actually needs.

    VERIFIED against a real captured payload (simulate-event, 2026-10-02):
      resource.payout_item_id, .transaction_id, .transaction_status,
      .payout_batch_id, .payout_item.{recipient_type, amount.{currency,value},
      .receiver, .note}, .payout_item_fee, .time_processed

    VERIFIED against a real completed checkout (2026-10-02, order
    52A89694AB3486153, USD 4,200.00): CHECKOUT.ORDER.* events use a COMPLETELY
    different shape —

      resource.purchase_units[0].amount.{currency_code,value}
      resource.purchase_units[0].payee.email_address
      resource.purchase_units[0].description / .invoice_id
      resource.payer.{email_address,name.{given_name,surname}}
      resource.payment_source.paypal.{email_address,account_id}

    The first version of this function only read the payout shape, so a genuine
    $4,200 checkout rendered with facts={} and the dashboard showed a headline
    with no amount. Order-shaped payloads are now read too.
    """
    facts: dict[str, Any] = {}
    pi = resource.get("payout_item") or {}
    amt = pi.get("amount") or {}

    def put(k, v):
        if v not in (None, "", {}, []):
            facts[k] = v

    # ---- payout shape -------------------------------------------------
    put("payout_item_id", resource.get("payout_item_id"))
    put("transaction_id", resource.get("transaction_id"))
    put("transaction_status", resource.get("transaction_status"))
    put("payout_batch_id", resource.get("payout_batch_id"))
    put("receiver", pi.get("receiver"))
    put("amount", _fmt_money(amt.get("value"), amt.get("currency", "")))
    put("currency", amt.get("currency"))
    put("note", pi.get("note"))
    put("fee", _fmt_money((resource.get("payout_item_fee") or {}).get("value"),
                           (resource.get("payout_item_fee") or {}).get("currency", "")))
    put("processed_at", resource.get("time_processed"))

    # ---- order/checkout shape -------------------------------------------
    units = resource.get("purchase_units") or []
    if units:
        u = units[0] or {}
        uamt = u.get("amount") or {}
        payer = resource.get("payer") or {}
        ps = (resource.get("payment_source") or {}).get("paypal") or {}
        name = (payer.get("name") or {}).get("given_name") or \
               (ps.get("name") or {}).get("given_name")
        surname = (payer.get("name") or {}).get("surname") or \
                  (ps.get("name") or {}).get("surname")
        put("amount", _fmt_money(uamt.get("value"), uamt.get("currency_code", "")))
        put("currency", uamt.get("currency_code"))
        put("order_id", resource.get("id"))
        put("order_status", resource.get("status"))
        put("payer", " ".join(x for x in (name, surname) if x) or
                    payer.get("email_address"))
        put("payer_email", payer.get("email_address") or ps.get("email_address"))
        put("payee", (u.get("payee") or {}).get("email_address"))
        put("description", u.get("description"))
        put("invoice_id", u.get("invoice_id"))
        put("country", ((payer.get("address") or {}).get("country_code")
                        or (ps.get("address") or {}).get("country_code")))

    # ---- generic fallbacks for non-payout, non-order events -------------
    for k in ("invoice_id", "event_status", "dispute_reason", "dispute_life_cycle_stage",
              "outcome", "custom_id"):
        put(k, resource.get(k))
    put("reason", (resource.get("reason") or {}).get("sub_description")
        if isinstance(resource.get("reason"), dict) else None)
    return facts


def explain(event: dict, severity: str = "info",
            verified: bool | None = None) -> Explanation:
    """Produce the explanation. Unknown event types still get a safe answer."""
    et = event.get("event_type", "UNKNOWN")
    spec = EXPLAINERS.get(et)

    if spec is None:
        return Explanation(
            event_type=et,
            event_id=event.get("id"),
            headline=f"PayPal event: {et.replace('.', ' ').lower()}",
            impact="This event type is not yet covered by the explainer.",
            cause=None,
            confidence="unknown",
            actions=["No action taken — unrecognised event types are logged, not acted on."],
            facts=extract_facts(event.get("resource") or {}),
            severity=severity, verified=verified,
        )

    return Explanation(
        event_type=et,
        event_id=event.get("id"),
        headline=spec["headline"],
        impact=spec["impact"],
        cause=spec.get("cause"),
        confidence=spec.get("confidence", "unknown"),
        actions=spec["actions"],
        facts=extract_facts(event.get("resource") or {}),
        severity=severity, verified=verified,
    )


# ── the outside reviewer (playbook rule 10) ──────────────────────────────────
def audit(explanations: list[Explanation]) -> dict:
    """
    Check our own output against rules we did not write ourselves.

    The point: a system consistent with itself cannot detect its own class of
    error. These checks are deliberately independent of the EXPLAINERS table —
    they read the OUTPUT and assert properties no explanation author controls.
    """
    findings = []
    seen = set()
    confirmed_by_event = []

    for e in explanations:
        if e.event_type in seen:
            findings.append(f"duplicate explanation emitted for {e.event_type}")
        seen.add(e.event_type)

        # We must never assert a cause we did not actually receive.
        # NOTE: "confirmed" with cause=None is NOT an error. For an event like
        # PAYMENT.PAYOUTS-ITEM.SUCCEEDED the arrival of the event IS the
        # confirmation — the payload states the outcome directly. Flagging that
        # was a false positive in the first version of this checker.
        if e.cause and e.confidence == "unknown":
            findings.append(f"{e.event_type}: has a cause but is marked 'unknown'")
        if e.confidence == "confirmed" and e.cause is None:
            # Legitimate, but the confidence must be justified by the event
            # itself. Record it so the distinction stays explicit.
            confirmed_by_event.append(f"{e.event_type}: outcome stated by the event itself")

        if not e.actions:
            findings.append(f"{e.event_type}: no action given — a user would not know what to do")

        for a in e.actions:
            if len(a) < 12:
                findings.append(f"{e.event_type}: action too vague to execute: {a!r}")

    return {
        "explanations_checked": len(explanations),
        "unique_event_types": len(seen),
        "issues": findings,
        "confirmed_by_event_itself": confirmed_by_event,
        "passed": not findings,
    }


if __name__ == "__main__":
    import sys
    from pathlib import Path

    if len(sys.argv) > 1 and Path(sys.argv[1]).exists():
        ev = json.load(open(sys.argv[1]))
        print(json.dumps(explain(ev).as_dict(), indent=2))
    else:
        print(__doc__)