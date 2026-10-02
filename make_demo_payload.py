#!/usr/bin/env python3
"""
make_demo_payload.py — mint a real, owned PayPal event for the demo video.

WHY THIS EXISTS
---------------
The demo was going to show `USD 1.00` to `beamdaddy@paypal.com`, because
/v1/notifications/simulate-event always replays PayPal's fixed documented
sample. That figure is not ours to choose, and "one dollar frozen" is a weak
stakes hook for a hackathon video.

So we mint our own. An INVOICE needs no buyer interaction — unlike an order,
which returns PAYER_ACTION_REQUIRED and needs a sandbox buyer to approve in a
browser (and sandbox accounts can only be created from the dashboard, not by
API). An invoice can be created, sent and cancelled purely by API.

Result: a genuine PayPal webhook carrying OUR figures — amount, currency,
invoice id, counterparty — delivered to our real endpoint and signature-verified
by PayPal's API. Not a mock, not a fixture.

Cost: $0. Sandbox only.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://api-m.sandbox.paypal.com"
CFG = Path("/root/.config/paypal")


def token() -> str:
    d = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    r = urllib.request.Request(
        f"{BASE}/v1/oauth2/token", data=d, method="POST",
        headers={
            "Authorization": "Basic "
            + base64.b64encode(
                f"{(CFG/'client_id').read_text().strip()}:"
                f"{(CFG/'sandbox_secret').read_text().strip()}".encode()
            ).decode(),
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(r, timeout=30) as x:
        return json.load(x)["access_token"]


def call(tk, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Authorization": f"Bearer {tk}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(r, timeout=60) as x:
            return x.status, json.loads(x.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read() or b"{}"
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"error": raw.decode(errors="replace")[:400]}
    except Exception as e:
        return 0, {"error": f"{type(e).__name__}: {e}"}


def build_invoice(amount: str, currency: str, note: str, item: str,
                  invoice_number: str, recipient: str):
    return {
        "detail": {
            "currency_code": currency,
            "note": note,
            # Unique per run: PayPal rejects a reused invoice_number with
            # DUPLICATE_INVOICE_NUMBER, and the default sandbox account already
            # had HOLDS-0001 from an earlier run.
            "invoice_number": invoice_number,
            "memo": note,
        },
        "invoicer": {"nickname": "HoldWatch Demo"},
        "items": [
            {"name": item, "quantity": "1",
             "unit_amount": {"currency_code": currency, "value": amount}}
        ],
        "configuration": {
            "allow_partial_payments": False,
            "tax_calc_mode": "NONE",
        },
        # Recipient shape, taken from the live OpenAPI schema
        # (developer.paypal.com/api/invoicing/v2/schema.json):
        #   invoice.primary_recipients[] -> recipient_info -> billing_info.email_address
        # A flat {"email_address": ...} at the recipient level is SILENTLY DROPPED
        # — the invoice returns primary_recipients: null and /send then fails
        # 422 MISSING_RECIPIENT_EMAIL. Nesting it correctly fixes both.
        # Sandbox-safe address; nothing is actually delivered to it.
        "primary_recipients": [
            {"billing_info": {"email_address": recipient}}
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--amount", default="4200.00")
    ap.add_argument("--currency", default="USD")
    ap.add_argument("--note", default="Client retainer — March")
    ap.add_argument("--item", default="Design retainer, delivered")
    ap.add_argument("--save", default="/root/web3alphatester/paypal/demo_invoice.json")
    ap.add_argument("--invoice-number", default=None,
                    help="defaults to HOLDS-<timestamp> to stay unique per run")
    ap.add_argument("--recipient", default="buyer@personal.example.com",
                    help="sandbox-safe address; nothing is delivered to it")
    a = ap.parse_args()

    inv_no = a.invoice_number or f"HOLDS-{int(time.time())}"

    tk = token()
    print("auth OK")

    print(f"creating invoice {a.currency} {a.amount} (no. {inv_no}) …")
    c, inv = call(tk, "POST", "/v2/invoicing/invoices",
                  build_invoice(a.amount, a.currency, a.note, a.item,
                                inv_no, a.recipient))
    print(f"  HTTP {c}")
    if c not in (200, 201):
        print(json.dumps(inv, indent=2)[:900])
        return 1

    # The 201 body is NOT the invoice. Two shapes have been observed:
    #   {"rel":"self","href":".../invoices/INV2-XXXX","method":"GET"}   (bare)
    #   {"links":[{"rel":"self","href":".../invoices/INV2-XXXX"}, ...]} (wrapped)
    # Neither carries "id", so a plain .get("id") silently yields None and the
    # send step 404s. Accept either, and fail loudly if neither resolves.
    iid = inv.get("id")
    if not iid:
        candidates = []
        if inv.get("href"):
            candidates.append(inv["href"])
        for link in inv.get("links") or []:
            if isinstance(link, dict) and link.get("href"):
                candidates.append(link["href"])
        for href in candidates:
            if "/invoices/" in href:
                iid = href.rstrip("/").rsplit("/", 1)[-1]
                break
    if not iid:
        print("could not resolve an invoice id from the create response:")
        print(json.dumps(inv, indent=2)[:600])
        return 1

    print(f"  invoice_id : {iid}")
    c2, full = call(tk, "GET", f"/v2/invoicing/invoices/{iid}")
    print(f"  fetch      : HTTP {c2}  status={full.get('status')}")
    print(f"  amount     : {json.dumps(full.get('amount'))}")
    print(f"  number     : {full.get('detail', {}).get('invoice_number')}")
    print(f"  note       : {full.get('detail', {}).get('note')}")
    if c2 != 200:
        print(json.dumps(full, indent=2)[:600])
        return 1

    # Send it. This is what makes PayPal emit real CHECKOUT.ORDER.* webhooks
    # for an app we own — the payload carries OUR invoice figures.
    print("sending invoice (triggers real webhooks) …")
    cs, sent = call(tk, "POST", f"/v2/invoicing/invoices/{iid}/send",
                    {"subject": a.note})
    print(f"  send HTTP {cs}  status={sent.get('status')}")

    Path(a.save).write_text(json.dumps(full, indent=2))
    print(f"\nsaved -> {a.save}")
    print("\nINVOICE_ID=" + str(iid))
    print(f"AMOUNT={a.currency} {a.amount}")
    return 0


if __name__ == "__main__":
    sys.exit(main())