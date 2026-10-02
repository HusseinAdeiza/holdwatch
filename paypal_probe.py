#!/usr/bin/env python3
"""
paypal_probe.py — verify sandbox credentials, and answer the one question that
decides whether the project is buildable:

    Does Transaction Search work for a plain sandbox REST app?

Per PayPal's docs, Transaction Search is exposed by toggling it in the app's
"Sandbox App Settings". If it is off, or restricted to partners, every rule in
hold_signals.py loses its primary input and the project changes shape.

Credentials are read from disk, never from argv (argv leaks into shell history
and process listings) and never printed:

    /root/.config/paypal/client_id      # public, mode 644 is fine
    /root/.config/paypal/sandbox_secret # private, mode 600

Usage:
    python3 paypal_probe.py            # full probe
    python3 paypal_probe.py --auth-only # just prove the credential works
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = "https://api-m.sandbox.paypal.com"
CFG = Path("/root/.config/paypal")

# Endpoints we are testing, in the order that fails most informatively.
PROBES = [
    ("balances",       "/v1/reporting/balances"),
    ("transactions",   "/v1/reporting/transactions"),
    ("disputes_list",  "/v1/customer/disputes?limit=1"),
    ("invoices_list",  "/v2/invoicing/invoices?page=1&page_size=1"),
    ("orders_list",    "/v2/checkout/orders?page=1&page_size=1"),
    ("webhooks_list",  "/v1/notifications/webhooks"),
]


def _read(name: str) -> str | None:
    p = CFG / name
    if not p.exists():
        return None
    v = p.read_text().strip()
    return v or None


def get_token(client_id: str, secret: str) -> str:
    """client_credentials grant. Never logs the secret."""
    data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    req = urllib.request.Request(
        f"{BASE}/v1/oauth2/token", data=data, method="POST",
        headers={
            "Authorization": "Basic " + _b64(f"{client_id}:{secret}"),
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["access_token"]


def _b64(s: str) -> str:
    import base64
    return base64.b64encode(s.encode()).decode()


def call(token: str, path: str, params: dict | None = None) -> tuple[int, dict]:
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        body = e.read() or b"{}"
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, {"raw": body.decode(errors="replace")[:300]}
    except Exception as e:  # network/DNS/TLS
        return 0, {"error": f"{type(e).__name__}: {e}"}


def main() -> int:
    client_id = _read("client_id")
    secret = _read("sandbox_secret")

    print("=" * 74)
    print("PayPal sandbox probe")
    print("=" * 74)

    missing = [n for n, v in (("client_id", client_id),
                              ("sandbox_secret", secret)) if not v]
    if missing:
        print(f"MISSING: {', '.join(missing)}")
        print(f"  client_id      -> echo -n '…' > {CFG/'client_id'}")
        print(f"  sandbox_secret -> echo -n '…' > {CFG/'sandbox_secret'}")
        print("\nThe client ID is public and can be pasted in chat.")
        print("For the secret, write it to the file yourself so it never")
        print("enters this conversation.")
        return 2

    print(f"client_id   : {client_id[:10]}…{client_id[-6:]}  (len {len(client_id)})")
    print(f"secret      : loaded from disk, {len(secret)} chars, never printed")
    print()

    # 1. auth
    try:
        token = get_token(client_id, secret)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        print(f"AUTH FAILED  HTTP {e.code}")
        print(f"  {detail}")
        print("\nUsual causes:")
        print("  - the secret is from the LIVE tab, not the SANDBOX tab")
        print("  - trailing newline or quotes written into the file")
        print("  - app was deleted/regenerated in the dashboard")
        return 1
    except Exception as e:
        print(f"AUTH ERROR  {type(e).__name__}: {e}")
        return 1

    print("AUTH OK  — access token obtained (not printed)")

    if "--auth-only" in sys.argv:
        return 0

    # 2. endpoint probes
    end = datetime.now(timezone.utc) - timedelta(days=7)
    start = end - timedelta(days=30)

    params_by_probe = {
        "transactions": {
            "start_date": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_date": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "fields": "transaction_id,transaction_status,transaction_event_code,"
                      "payer_email,payer_name,amount,currency_code,net_amount,"
                      "fee_amount,transaction_initiation_date,transaction_updated_date",
        },
        "balances": {},
        "disputes_list": {},
        "invoices_list": {},
        "orders_list": {},
        "webhooks_list": {},
    }

    print()
    results = {}
    for name, path in PROBES:
        code, body = call(token, path, params_by_probe.get(name))
        results[name] = {"status": code, "body_keys": list(body)[:8]}
        mark = {200: "OK ", 201: "OK ", 204: "OK ", 401: "AUTHZ", 403: "DENIED",
                404: "NOPE", 400: "BAD ", 0: "NET!"}.get(code, f"{code}")
        note = ""
        if name == "transactions" and code == 200:
            items = body.get("transaction_info") or body.get("account_activity")
            note = f"  {len(items or [])} transactions in range"
        elif code == 403 and name == "transactions":
            note = "  <-- THIS IS THE BLOCKING CASE"
        elif code == 404:
            note = "  (not enabled for this app)"
        print(f"  {mark}  {name:16s} HTTP {code}{note}")
        if code == 403 or (code == 0):
            d = body.get("details") or body.get("error") or body.get("name") or ""
            if d:
                print(f"        {str(d)[:150]}")

    with open("/root/web3alphatester/paypal/probe_report.json", "w") as f:
        json.dump(results, f, indent=2)

    tx = results.get("transactions", {})
    print()
    if tx.get("status") == 200:
        print("VERDICT: Transaction Search WORKS for this sandbox app.")
        print("  The rule set in hold_signals.py can be calibrated against")
        print("  real sandbox data. Project is buildable as designed.")
    elif tx.get("status") in (403, 404):
        print("VERDICT: Transaction Search NOT available to this app.")
        print("  Do NOT build around it. Next step is a different primary")
        print("  input — see PAYPAL_HAKATHON.md for the fallback options.")
    else:
        print("VERDICT: inconclusive. Re-run; sandbox data can lag ~3h.")
    print("\n  full results -> paypal/probe_report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())