#!/usr/bin/env python3
"""
register_webhook.py — subscribe an HTTPS endpoint to PayPal webhook events.

Why this exists
---------------
The PayPal developer dashboard does NOT expose webhook registration. The docs say to
subscribe an endpoint for your app, but there is no UI control for it. The only way is
the API:

    POST /v1/notifications/webhooks

This script does that, and is idempotent: re-running updates the existing webhook
rather than creating duplicates.

Usage:
    python3 register_webhook.py https://your-endpoint.example.com
    python3 register_webhook.py https://your-endpoint.example.com --all   # all 18 events
    python3 register_webhook.py --list                                   # show current

Credentials are read from /root/.config/paypal/, never argv, never printed.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://api-m.sandbox.paypal.com"
CFG = Path("/root/.config/paypal")
WID_FILE = CFG / "webhook_id"

# The 18 events HoldWatch subscribes to: the restriction and money-movement signals.
# Deliberately not "*" — an unfiltered stream is mostly noise, and the product only
# explains these types.
EVENTS = [
    "PAYMENT.PAYOUTS-ITEM.HELD",
    "PAYMENT.PAYOUTS-ITEM.BLOCKED",
    "PAYMENT.PAYOUTS-ITEM.FAILED",
    "PAYMENT.PAYOUTS-ITEM.RETURNED",
    "PAYMENT.PAYOUTS-ITEM.SUCCEEDED",
    "CHECKOUT.PAYMENT-RESOURCE.PAYMENT-ON-HOLD",
    "CHECKOUT.PAYMENT-RESOURCE.PAYMENT-COMPLETED",
    "CHECKOUT.ORDER.APPROVED",
    "CHECKOUT.ORDER.COMPLETED",
    "CHECKOUT.ORDER.DECLINED",
    "CUSTOMER.ACCOUNT-ENTITIES.CAPABILITY-UPDATED",
    "CUSTOMER.ACCOUNT-ENTITIES.REQUIREMENTS-UPDATED",
    "CUSTOMER.PAYPAL-ACCOUNT.CHANGED",
    "CUSTOMER.PROFILE.ACCOUNT-CLOSED",
    "RISK.DISPUTE.CREATED",
    "CUSTOMER.DISPUTE.CREATED",
    "CUSTOMER.DISPUTE.RESOLVED",
    "BILLING.SUBSCRIPTION.PAYMENT.FAILED",
]


def get_token() -> str:
    cid = (CFG / "client_id").read_text().strip()
    sec = (CFG / "sandbox_secret").read_text().strip()
    data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    req = urllib.request.Request(
        f"{BASE}/v1/oauth2/token", data=data, method="POST",
        headers={
            "Authorization": "Basic " + base64.b64encode(f"{cid}:{sec}".encode()).decode(),
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["access_token"]


def call(token: str, method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read() or b"{}"
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"error": raw.decode(errors="replace")[:300]}
    except Exception as e:
        return 0, {"error": f"{type(e).__name__}: {e}"}


def list_webhooks(token: str):
    code, body = call(token, "GET", "/v1/notifications/webhooks")
    return code, body.get("webhooks") or []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?", help="public HTTPS endpoint to subscribe")
    ap.add_argument("--list", action="store_true", help="show current webhooks")
    ap.add_argument("--all", action="store_true", help="subscribe all 18 events")
    ap.add_argument("--delete", action="store_true", help="remove the stored webhook")
    ap.add_argument("--keep-others", action="store_true",
                    help="do not remove webhook subscriptions registered on other URLs")
    a = ap.parse_args()

    if not (CFG / "client_id").exists() or not (CFG / "sandbox_secret").exists():
        print("credentials missing: need ~/.config/paypal/{client_id,sandbox_secret}")
        return 2

    token = get_token()

    if a.list:
        code, hooks = list_webhooks(token)
        print(f"HTTP {code} — {len(hooks)} webhook(s)")
        for w in hooks:
            print(f"  {w.get('id')}  ->  {w.get('url')}  ({len(w.get('event_types', []))} events)")
        return 0

    if a.delete:
        if WID_FILE.exists():
            wid = WID_FILE.read_text().strip()
            code, _ = call(token, "DELETE", f"/v1/notifications/webhooks/{wid}")
            print(f"delete {wid} -> HTTP {code}")
            WID_FILE.unlink(missing_ok=True)
        else:
            print("no stored webhook id")
        return 0

    if not a.url:
        ap.print_help()
        return 2

    if not a.url.startswith("https://"):
        print("PayPal requires an HTTPS endpoint — https:// required, got:", a.url)
        return 2

    events = EVENTS if a.all else EVENTS[:1]
    body = {"url": a.url, "event_types": [{"name": e} for e in events]}

    # Idempotency, established by testing against the real API (2026-10-02):
    #   PUT  /v1/notifications/webhooks/{id}  -> 404  (no update verb exists)
    #   POST with an already-registered url  -> 400 WEBHOOK_URL_ALREADY_EXISTS
    # So the ONLY way to change a subscription is delete-then-create. The gap is
    # unavoidable; it lasts one API call and only occurs when re-registering.
    code, hooks = list_webhooks(token)
    existing = next((w for w in hooks if w.get("url") == a.url), None)
    old_id = existing["id"] if existing else None

    # PayPal allows multiple webhook subscriptions, so creating one for a NEW url
    # does NOT displace an old one. Matching only on the target url therefore
    # left the previous (now dead) tunnel subscribed when re-pointing, which is
    # how a stale subscription silently survives a migration.
    #
    # Purge any subscription whose host differs from the one we're registering,
    # unless --keep-others is passed. PayPal delivers each event to EVERY
    # matching subscription, so a second live one would double-count events.
    if not a.keep_others:
        for w in hooks:
            wid, wurl = w.get("id"), w.get("url", "")
            if not wid or wurl == a.url:
                continue
            dcode, dout = call(token, "DELETE", f"/v1/notifications/webhooks/{wid}")
            print(f"  removed stale subscription {wid} -> {wurl} (HTTP {dcode})")

    if old_id:
        dcode, dout = call(token, "DELETE", f"/v1/notifications/webhooks/{old_id}")
        print(f"  removed existing {old_id} (HTTP {dcode})")
        if dcode not in (200, 204):
            # Do not create a replacement if the delete failed — we would end up
            # with two webhooks on one URL, or none.
            print(json.dumps(dout, indent=2)[:600])
            return 1

    code, body_out = call(token, "POST", "/v1/notifications/webhooks", body)
    if code not in (200, 201):
        print(f"webhook create: HTTP {code}")
        print(json.dumps(body_out, indent=2)[:900])
        return 1

    new_id = body_out.get("id")
    action = "replaced" if old_id else "created"

    print(f"webhook {action}: HTTP {code}")
    if new_id:
        WID_FILE.write_text(new_id)
    print(f"  id     : {new_id}")
    print(f"  url    : {body_out.get('url')}")
    print(f"  events : {len(body_out.get('event_types', []))} subscribed")
    print(f"  saved  : {WID_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())