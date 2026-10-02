#!/usr/bin/env python3
"""
enrich.py — resolve an event to its full PayPal record.

WHY THIS EXISTS
---------------
A real capture fired on 2026-10-02 (order 52A89694AB3486153, USD 4,200.00,
capture 6YH19408NM0071141) but PayPal delivered NO webhook for it — the
receiver stayed at 9 events. We verified the capture through
GET /v2/payments/captures/{id}, which returns 200.

That matters for the product, not just the demo: some PayPal state changes are
readable by API but not always delivered to a webhook. A monitor that only
listens is therefore incomplete. This module makes the listener able to ASK.

Design:
  - Never invents anything. If the API cannot be reached, the event is returned
    un-enriched and still explained.
  - Read-only. No money moves.
  - Cached, so a 5s dashboard poll does not hammer the API.

Usage:
    from enrich import enrich_event
    e = enrich_event(raw_event_dict)
"""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://api-m.sandbox.paypal.com"
CFG = Path("/root/.config/paypal")
CACHE_PATH = CFG / "enrich_cache.json"
CACHE_TTL = 60 * 30          # PayPal state changes; 30 min is plenty

_token_cache: tuple[float, str] | None = None
_cache: dict | None = None


def _token() -> str | None:
    """
    Read-only access token from disk-stored credentials.

    All credential resolution goes through config.py so a hosted deploy (env
    vars) and a local run (files) behave identically. Never logs, never raises.
    """
    import config
    return config.token()


def _load_cache() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(CACHE_PATH.read_text())
        except Exception:
            _cache = {}
    return _cache


def _put_cache(k: str, v: dict) -> None:
    global _cache
    c = _load_cache()
    c[k] = {"ts": time.time(), "v": v}
    _cache = c
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(c, indent=2))
    except Exception:
        pass


def _get(path: str):
    tok = _token()
    if not tok:
        return None
    req = urllib.request.Request(BASE + path,
                                 headers={"Authorization": f"Bearer {tok}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except Exception:
        return None


def enrich_event(event: dict) -> dict:
    """
    Return the event plus a "paypal_record" key when the full record could be
    resolved. Never raises; never blocks the explanation path.
    """
    res = event.get("resource") or {}
    et = event.get("event_type", "")
    key = f"{et}:{res.get('id')}"

    hit = _load_cache().get(key)
    if hit and time.time() - hit["ts"] < CACHE_TTL:
        return {**event, "paypal_record": hit["v"], "enriched_cached": True}

    record = None
    source = None

    if et.startswith("CHECKOUT.ORDER.") and res.get("id"):
        record = _get(f"/v2/checkout/orders/{res['id']}")
        source = "GET /v2/checkout/orders/{id}"

    elif et.startswith("PAYMENT.CAPTURE") and res.get("id"):
        record = _get(f"/v2/payments/captures/{res['id']}")
        source = "GET /v2/payments/captures/{id}"

    elif et.startswith("PAYMENT.PAYOUTS-ITEM") and res.get("payout_item_id"):
        record = _get(f"/v1/payments/payouts-item/{res['payout_item_id']}")
        source = "GET /v1/payments/payouts-item/{id}"

    if not record:
        return {**event, "paypal_record": None,
                "enrich_source": None,
                "enrich_note": "no resolvable record id in this payload"}

    if record:
        _put_cache(key, record)

    return {**event, "paypal_record": record, "enriched_cached": False,
            "enrich_source": source}


def resolve_capture(capture_id: str) -> dict | None:
    """Direct lookup by capture id — used when a capture webhook never fires."""
    return _get(f"/v2/payments/captures/{capture_id}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "--capture":
        print(json.dumps(resolve_capture(sys.argv[2]), indent=2))
    else:
        p = Path(sys.argv[1]) if len(sys.argv) > 1 else None
        if p and p.exists():
            print(json.dumps(enrich_event(json.loads(p.read_text())), indent=2))
        else:
            print(__doc__)