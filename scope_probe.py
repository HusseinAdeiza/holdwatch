#!/usr/bin/env python3
"""
scope_probe.py — map what THIS sandbox app can actually reach.

Context: paypal_probe.py proved the credential is valid (auth OK) but that
/v1/reporting/transactions returns 403 NOT_AUTHORIZED. That endpoint is the
restricted "Transaction Search" API — PayPal gates it behind an app-feature
toggle/partner status. It is NOT available to a default sandbox REST app.

This script does not assume the project is dead. It establishes what the app
CAN do, because the whole idea has to be re-anchored on an input we can
actually read. Rules first, sentiment later.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://api-m.sandbox.paypal.com"
CFG = Path("/root/.config/paypal")


def _read(n):
    p = CFG / n
    return p.read_text().strip() if p.exists() else None


def _b64(s):
    import base64
    return base64.b64encode(s.encode()).decode()


def token():
    data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    req = urllib.request.Request(f"{BASE}/v1/oauth2/token", data=data, method="POST",
        headers={"Authorization": "Basic " + _b64(f"{_read('client_id')}:{_read('sandbox_secret')}"),
                 "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["access_token"]


def call(tk, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
        headers={"Authorization": f"Bearer {tk}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            try: return r.status, json.loads(raw or b"{}")
            except Exception: return r.status, {"raw": raw.decode(errors='replace')[:200]}
    except urllib.error.HTTPError as e:
        raw = e.read() or b"{}"
        try: return e.code, json.loads(raw)
        except Exception: return e.code, {"raw": raw.decode(errors='replace')[:300]}
    except Exception as e:
        return 0, {"error": f"{type(e).__name__}: {e}"}


# ── read surfaces ────────────────────────────────────────────────────────────
READS = [
    ("identity:userinfo",      "GET",  "/v1/identity/oauth2/userinfo?schema=paypalv1.1", None),
    ("identity:userinfo_2",    "GET",  "/v1/identity/oauth2/userinfo?schema=paypalv2", None),
    ("reporting:balances",     "GET",  "/v1/reporting/balances", None),
    ("reporting:transactions", "GET",  "/v1/reporting/transactions", None),
    ("payments_list",          "GET",  "/v1/payments/payment", None),
    ("invoices_list",          "GET",  "/v2/invoicing/invoices?page=1&page_size=3", None),
    ("subscriptions_list",     "GET",  "/v1/billing/subscriptions?count=3", None),
    ("products_list",          "GET",  "/v1/catalogs/products", None),
    ("webhooks_list",          "GET",  "/v1/notifications/webhooks", None),
    ("disputes_list",          "GET",  "/v1/customer/disputes?limit=3", None),
    ("orders_list",            "GET",  "/v2/checkout/orders?page=1&page_size=3", None),
    ("tracking_list",          "GET",  "/v1/shipping/trackers-batch", None),
    ("commerce_merchants",     "GET",  "/v1/customer/partners", None),
    ("payment_methods",        "GET",  "/v1/payment-methods?customer=PACC", None),
]

# ── write surfaces: what a real product could CREATE and therefore observe ───
WRITES = [
    ("order_create",   "POST", "/v2/checkout/orders",
     {"intent":"CAPTURE","purchase_units":[{"amount":{"currency_code":"USD","value":"10.00"}}]}),
    ("invoice_create", "POST", "/v2/invoicing/invoices",
     {"detail":{"currency_code":"USD","note":"probe"}},
     {"invoice":{"billing_plan":[{"type":"MERCHANT_INITIATED_BILLING",
       "merchant_preferences":{"return_url":"https://example.com","cancel_url":"https://example.com"},
       "payment_preferences":{"auto_finalize":True,"payment_method":"PAYPAL"}}],
       "items":[{"name":"probe","quantity":"1","unit_amount":{"currency_code":"USD","value":"10.00"}}]}}),
    ("payout_create",  "POST", "/v2/payments/payouts", None),
    ("subscription",   "POST", "/v1/billing/subscriptions", None),
]


def show(label, code, body):
    mark = {200:"OK ",201:"OK ",204:"OK ",400:"BAD",401:"AUTHZ",403:"DENIED",
            404:"NOPE",422:"INVAL",0:"NET!"}.get(code, str(code))
    print(f"  {mark}  {label:24s} HTTP {code}")
    return code


def summarize(label, body):
    if not isinstance(body, dict):
        return
    for k in ("name","message","error","error_description"):
        if k in body:
            v = body[k]
            if isinstance(v, list):
                v = v[0]
            if isinstance(v, dict):
                d = v.get("details") or [v.get("description","")]
                v = d[0] if isinstance(d, list) and d else str(d)[:120]
            print(f"        {k}: {str(v)[:150]}")
            return


def main():
    tk = token()
    print("="*78); print("SCOPE MAP — what this sandbox app can actually reach")
    print("="*78)

    print("\nREAD surfaces")
    print("-"*78)
    ok_reads, denied = [], []
    for label, m, p, b in READS:
        code, body = call(tk, m, p, b)
        show(label, code, body)
        if code in (200, 201, 204): ok_reads.append((label, body))
        if code in (401, 403): denied.append(label)
        if code in (400, 404, 403) or code == 200:
            summarize(label, body)
        if code == 200:
            for key in ("transaction_info","account_activity","items","total_items",
                        "webhooks","invoices","payment_instructions","units"):
                v = body.get(key)
                if isinstance(v, list):
                    print(f"        -> {key}: {len(v)} entries")
                    break

    print("\nWRITE surfaces (can we create the data we'd then observe?)")
    print("-"*78)
    ok_writes = []
    for spec in WRITES:
        label, m, p, *rest = spec
        body = rest[0] if rest else None
        code, resp = call(tk, m, p, body)
        show(label, code, resp)
        if code in (200, 201, 204): ok_writes.append(label)
        if code in (400, 401, 403, 404): summarize(label, resp)

    print("\n" + "="*78)
    print(f"READABLE : {', '.join(l for l,_ in ok_reads) or 'none'}")
    print(f"DENIED   : {', '.join(denied) or 'none'}")
    print(f"WRITABLE : {', '.join(ok_writes) or 'none'}")
    print("="*78)

    # What a hold-detection product could actually observe:
    observable = set()
    if any("orders" in w for w in ok_writes) and any("orders" in l for l,_ in ok_reads):
        observable.add("payment lifecycle via Orders (create -> capture -> status)")
    if any("invoice" in w for w in ok_writes) and any("invoice" in l for l,_ in ok_reads):
        observable.add("invoice lifecycle + disputes via Invoicing")
    if any("subscription" in w for w in ok_writes):
        observable.add("subscription lifecycle")
    if any("webhooks" in l for l,_ in ok_reads):
        observable.add("real-time event stream via webhooks")
    if any("identity" in l for l,_ in ok_reads):
        observable.add("account identity/profile fields")
    if any("payments" in l for l,_ in ok_reads):
        observable.add("payment records")

    print("\nOBSERVABLE BY THIS APP:")
    for o in sorted(observable) or ["  (nothing yet — see denied list)"]:
        print(f"  + {o}")

    with open("/root/web3alphatester/paypal/scope_report.json","w") as f:
        json.dump({"readable":[l for l,_ in ok_reads],"denied":denied,
                   "writable":ok_writes,"observable":sorted(observable)}, f, indent=2)
    print("\n  -> paypal/scope_report.json")


if __name__ == "__main__":
    sys.exit(main())