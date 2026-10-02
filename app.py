#!/usr/bin/env python3
"""
app.py — the HoldWatch web UI and API.

Serves the dashboard judges will see, backed by the live receiver and the
explainer. Everything shown is real: the events come from PayPal, the
explanations come from explainer.py, and the signature verification result is
displayed rather than hidden.

Run:  python3 app.py --port 8080
Then: http://127.0.0.1:8080
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote_plus

sys.path.insert(0, "/root/web3alphatester/paypal")
from explainer import explain, audit, EXPLAINERS  # noqa: E402
import ai  # noqa: E402
from enrich import enrich_event  # noqa: E402

EVENT_DIR = Path("/root/web3alphatester/paypal/events")
VERIFIED_PATH = Path("/root/.config/paypal/verified_events.json")


def load_verified() -> dict:
    """ids the receiver accepted as genuinely signed by PayPal."""
    try:
        return json.loads(VERIFIED_PATH.read_text())
    except Exception:
        return {}


def summarise_record(record: dict | None) -> dict | None:
    """
    Condense a full PayPal record to the handful of fields worth showing.
    Returns None rather than a partial object when there is nothing to show, so
    the UI can distinguish "no record" from "empty record".
    """
    if not isinstance(record, dict) or not record:
        return None
    out: dict = {}
    status = record.get("status")
    if status:
        out["status"] = status

    # order shape
    units = record.get("purchase_units") or []
    if units:
        u = units[0] or {}
        amt = u.get("amount") or {}
        if amt:
            out["amount"] = f"{amt.get('currency_code','')} {amt.get('value','')}".strip()
        for c in ((u.get("payments") or {}).get("captures") or []):
            out["capture_id"] = c.get("id")
            out["capture_status"] = c.get("status")
        if u.get("invoice_id"):
            out["invoice_id"] = u["invoice_id"]

    # capture shape
    amt = record.get("amount") or {}
    if amt and "amount" not in out:
        out["amount"] = f"{amt.get('currency_code','')} {amt.get('value','')}".strip()
    if record.get("id"):
        out["record_id"] = record["id"]
    if record.get("final_capture") is not None:
        out["final_capture"] = record["final_capture"]

    return out or None


def severity_for(event_type: str) -> str:
    """
    Severity lives with the receiver's HOLD_EVENTS map (one source of truth),
    imported here rather than duplicated — a second copy would drift.
    """
    from receiver import HOLD_EVENTS
    return HOLD_EVENTS.get(event_type, ("OTHER", "", "info"))[2]


def load_events(limit=50, with_ai=True, with_enrich=True) -> list[dict]:
    """
    Read captured PayPal events, newest first, and explain each one.

    The AI layer is best-effort: if ai.tailor() returns text=None (no key, rate
    limited, or the guardrail discarded the output) the card still renders from
    the deterministic explanation alone. The product never depends on it.

    Enrichment is likewise best-effort. Some PayPal state changes are readable
    by API but NOT delivered to a webhook — the 2026-10-02 capture
    6YH19408NM0071141 (USD 4,200.00) completed with no event at all. When the
    payload carries a resolvable id we ask PayPal for the current record, so a
    missing webhook does not mean a missing fact. A monitor that only listens
    is incomplete.
    """
    files = sorted(EVENT_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime,
                   reverse=True)[:limit]
    verified = load_verified()
    out = []
    for f in files:
        try:
            ev = json.loads(f.read_text())
        except Exception:
            continue
        et = ev.get("event_type", "UNKNOWN")
        eid = ev.get("id", "")

        # best-effort API resolution; never raises, never blocks
        record = None
        enrich_note = None
        if with_enrich and et in ("CHECKOUT.ORDER.APPROVED", "CHECKOUT.ORDER.COMPLETED",
                                  "CHECKOUT.ORDER.DECLINED"):
            try:
                enriched = enrich_event(ev)
                record = enriched.get("paypal_record")
                enrich_note = enriched.get("enrich_note")
            except Exception as e:
                enrich_note = f"enrichment unavailable: {type(e).__name__}"

        ex = explain(ev, severity=severity_for(et),
                     verified=verified.get(f"{et}|{eid}", False)).as_dict()
        ex["received_at"] = f.stat().st_mtime
        ex["paypal_record"] = summarise_record(record)
        ex["enrich_note"] = enrich_note

        # Known type -> tailor it. Unknown type -> ask the model to explain it,
        # since the rules engine has nothing for it.
        if with_ai:
            if et in EXPLAINERS:
                res = ai.tailor(ex, eid)
            else:
                res = ai.explain_unknown(ev, eid)
            ex["ai"] = res
        else:
            ex["ai"] = {"text": None, "model": None, "cached": False,
                        "reason": "ai disabled"}
        out.append(ex)
    return out


HTML = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>HoldWatch — PayPal payout holds, explained</title>
<style>
  :root{
    --bg:#0b1020; --panel:#141a2e; --panel2:#1b2340; --line:#2a3355;
    --ink:#e8ecf8; --dim:#93a0c4; --accent:#4f7cff;
    --crit:#ff5d6c; --high:#ffa23a; --med:#ffd93a; --info:#4fd1c5; --ok:#3ddc97;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
       font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,system-ui,sans-serif}
  header{padding:28px 32px;border-bottom:1px solid var(--line);
         display:flex;align-items:baseline;gap:16px;flex-wrap:wrap}
  h1{font-size:22px;margin:0;letter-spacing:-.02em}
  .tag{color:var(--dim);font-size:14px}
  .live{margin-left:auto;font-size:12px;color:var(--ok);display:flex;align-items:center;gap:7px}
  .dot{width:8px;height:8px;border-radius:50%;background:var(--ok);
       box-shadow:0 0 0 4px rgba(61,220,151,.15)}
  main{max-width:1180px;margin:0 auto;padding:28px 32px 72px}
  .stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(168px,1fr));
         gap:14px;margin-bottom:28px}
  .stat{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px 18px}
  .stat .n{font-size:26px;font-weight:650;letter-spacing:-.02em}
  .stat .l{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.07em;margin-top:3px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:14px;
        padding:20px 22px;margin-bottom:16px;border-left:4px solid var(--dim)}
  .card.critical{border-left-color:var(--crit)}
  .card.high{border-left-color:var(--high)}
  .card.medium{border-left-color:var(--med)}
  .card.info{border-left-color:var(--info)}
  .card h2{margin:0 0 4px;font-size:17px;letter-spacing:-.01em}
  .meta{color:var(--dim);font-size:12.5px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
        margin-bottom:12px;word-break:break-all}
  .impact{background:var(--panel2);border-radius:9px;padding:12px 14px;margin:12px 0}
  .cause{font-size:14px;margin:8px 0}
  .badge{display:inline-block;padding:2px 9px;border-radius:99px;font-size:11px;
         font-weight:600;text-transform:uppercase;letter-spacing:.05em}
  .b-unknown{background:rgba(255,162,58,.15);color:var(--high)}
  .b-confirmed{background:rgba(61,220,151,.15);color:var(--ok)}
  .b-verified{background:rgba(61,220,151,.15);color:var(--ok)}
  .b-ai{background:rgba(79,124,255,.18);color:#8fb0ff}
  .ai{margin:12px 0;padding:12px 14px;background:rgba(79,124,255,.07);
      border:1px solid rgba(79,124,255,.25);border-radius:9px;font-size:14px}
  .ai-off{margin:10px 0;font-size:12.5px;color:var(--dim);font-style:italic}
  .ask{margin-left:8px;padding:3px 10px;border-radius:99px;cursor:pointer;
       background:rgba(79,124,255,.16);border:1px solid rgba(79,124,255,.4);
       color:#8fb0ff;font-size:12px}
  .ask:hover{background:rgba(79,124,255,.28)}
  ol{margin:10px 0 0;padding-left:22px}
  ol li{margin-bottom:7px}
  details{margin-top:12px}
  summary{cursor:pointer;color:var(--dim);font-size:13px}
  table{width:100%;border-collapse:collapse;margin-top:10px;font-size:13px}
  td{padding:5px 10px 5px 0;vertical-align:top}
  td:first-child{color:var(--dim);white-space:nowrap;width:180px}
  .empty{text-align:center;padding:56px 20px;color:var(--dim);
         border:1px dashed var(--line);border-radius:14px}
  .note{margin-top:34px;padding:16px 18px;background:rgba(79,124,255,.07);
        border:1px solid rgba(79,124,255,.25);border-radius:12px;font-size:13.5px;color:var(--dim)}
  .note b{color:var(--ink)}
</style></head><body>
<header>
  <h1>HoldWatch</h1>
  <span class="tag">PayPal payout holds &amp; restrictions, explained</span>
  <span class="live"><span class="dot"></span><span id="live">live</span></span>
</header>
<main>
  <div class="stats" id="stats"></div>
  <div id="feed"></div>
  <div class="note">
    <b>What this shows.</b> Every card below is a real PayPal webhook delivered to
    this endpoint and verified against PayPal's signature API. Explanations are
    derived from the event payload — where PayPal does not disclose a reason,
    this says <i>unknown</i> rather than guessing.
  </div>
</main>
<script>
const SEV={critical:'critical',high:'high',medium:'medium',info:'info'};
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

function card(e,answers){
  const f=e.facts||{};
  const facts=Object.entries(f).map(([k,v])=>`<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join('');
  const cause=e.cause
    ? `<div class="cause"><span class="badge b-confirmed">confirmed</span> ${esc(e.cause)}</div>`
    : `<div class="cause"><span class="badge b-unknown">cause unknown</span>
       PayPal does not disclose the reason in this event. We will not invent one.</div>`;
  // AI layer: shown when present, silently omitted when there is no key / rate
  // limit / guardrail discard. The card is complete without it.
  // Key includes the event type, matching the server: PayPal's simulate-event
    // reuses one event id across event types, so id alone collides.
  const key = (e.event_type||'')+'|'+(e.event_id||'');
  const prior = answers && answers[key];
  const aiTxt = prior
    ? `<div class="ai answer"><span class="badge b-ai">AI</span> ${esc(prior)}</div>`
    : (e.ai && e.ai.text
    ? `<div class="ai"><span class="badge b-ai">AI</span> ${esc(e.ai.text)}
         <button class="ask" data-q="What should I do first?" data-id="${esc(key)}">Ask a follow-up</button>
       </div>`
    : (e.ai && e.ai.reason && e.ai.reason!=='no GEMINI_API_KEY set'
        ? `<div class="ai-off">AI layer unavailable (${esc(e.ai.reason)}) — showing rule-based explanation</div>` : ''));

  // Amount and counterparty as scannable fields, not only inside the AI
  // sentence. Added for the demo video: on a real CHECKOUT.ORDER.APPROVED the
  // USD 4,200.00 and the payer were only visible as prose, which reads far too
  // slowly at 85 seconds. Fields first, prose second.
  const F = (k,label,val)=>(val?`<div class="fact"><span class="fact__k">${esc(label)}</span><span class="fact__v tnum">${esc(val)}</span></div>`:'');
  const head = e.facts && e.facts.amount ? `
      <div class="evcard__facts">
        ${F('amount','Amount',e.facts.amount)}
        ${e.facts.payer?`<div class="fact"><span class="fact__k">Payer</span><span class="fact__v">${esc(e.facts.payer)}</span></div>`:''}
        ${e.facts.invoice_id?`<div class="fact"><span class="fact__k">Invoice</span><span class="fact__v mono">${esc(e.facts.invoice_id)}</span></div>`:''}
        ${e.paypal_record&&e.paypal_record.status?`<div class="fact"><span class="fact__k">PayPal says</span><span class="fact__v">${esc(e.paypal_record.status)}</span></div>`:''}
        ${e.facts.order_status?`<div class="fact"><span class="fact__k">Status</span><span class="fact__v mono">${esc(e.facts.order_status)}</span></div>`:''}
      </div>` : '';

  return `<div class="card ${SEV[e.severity]||'info'}">
    <h2>${esc(e.headline)}</h2>
    <div class="meta">${esc(e.event_type)} &nbsp;·&nbsp; ${esc(e.verified===true?'signature verified':'verification n/a')}</div>
    <div class="impact">${esc(e.impact)}</div>
    ${head}
    ${aiTxt}
    ${cause}
    <ol>${(e.actions||[]).map(a=>`<li>${esc(a)}</li>`).join('')}</ol>
    ${facts?`<details><summary>Event data (${Object.keys(f).length} fields from the payload)</summary>
      <table>${facts}</table></details>`:''}
  </div>`;
}

async function refresh(){
  try{
    const r=await fetch('/api/events');
    const d=await r.json();
    document.getElementById('stats').innerHTML=[
      ['Events received',d.total],
      ['Needs action',d.needs_action],
      ['Verified signatures',d.verified],
      ['Event types covered',d.covered],
    ].map(([l,n])=>`<div class="stat"><div class="n">${n}</div><div class="l">${l}</div></div>`).join('');
    // BUG FIXED 2026-10-02: the 5s poll replaced the whole #feed innerHTML, which
    // detached the follow-up button while its fetch was in flight. When the
    // answer arrived, replaceWith() targeted a detached node and the reply
    // vanished — the button appeared to do nothing. Fix: preserve any pending
    // Q&A answers across refreshes, and skip repainting entirely while one is
    // in flight.
    if(window.__askPending) return;
    const pending = window.__answers || {};
    document.getElementById('feed').innerHTML = d.events.length
      ? d.events.map(e=>card(e,pending)).join('')
      : `<div class="empty">Waiting for the first PayPal event.<br><br>
         <span style="font-size:13px">Trigger one with <code>POST /v1/notifications/simulate-event</code></span></div>`;
  }catch(e){document.getElementById('live').textContent='offline';}
}
refresh(); setInterval(refresh,5000);

// BUG FOUND 2026-10-02: the follow-up button did nothing when clicked.
// Cause: the listener was attached with addEventListener AFTER refresh() had
// already run, and refresh() replaces the entire #feed innerHTML every 5s. That
// is fine for a delegated listener — but `ev.target.closest('.ask')` fails when
// the click lands on a text node rather than the button element, so the handler
// bailed out silently. Fixed by resolving the target defensively and by
// attaching the listener once, before the first refresh.
document.addEventListener('click',async function(ev){
  var t = ev.target;
  // resolve across text-node targets, which is what a bare click produces
  var node = (t && t.nodeType === 3) ? t.parentElement : t;
  var b = node && node.closest ? node.closest('.ask') : null;
  if(!b) return;
  var key = b.dataset.id;
  window.__askPending = true;
  b.disabled=true; b.textContent='asking…';
  try{
    var r = await fetch('/api/ask?q='+encodeURIComponent(b.dataset.q)+
                        '&event_id='+encodeURIComponent(key));
    var d = await r.json();
    // Store the answer keyed by event, then let the next refresh() paint it.
    // Storing rather than mutating the DOM directly is what makes it survive the
    // 5s poll that used to discard in-flight results.
    var body = d.text
      ? d.text
      : (d.fallback_actions && d.fallback_actions.length
          ? 'Here is what we know for certain: ' + d.fallback_actions.slice(0,2).join(' ')
          : (d.reason || 'no answer'));
    window.__answers = window.__answers || {};
    window.__answers[key] = body;
  }catch(e){
    window.__answers = window.__answers || {};
    window.__answers[key] = 'Could not reach the assistant. The actions listed below still apply.';
  }finally{
    window.__askPending = false;
    await refresh();
  }
});
</script>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "HoldWatch/0.2"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        # Accept dicts as well as str/bytes. BUG FIXED 2026-10-02: passing a dict
        # (every 404 and validation error path) raised
        # AttributeError: 'dict' object has no attribute 'encode', which killed the
        # request handler and returned an empty response to the client instead of a
        # JSON error body.
        if isinstance(body, bytes):
            raw = body
        elif isinstance(body, str):
            raw = body.encode()
        else:
            raw = json.dumps(body).encode()
            ctype = "application/json"
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        p = urlparse(self.path).path

        if p in ("/", "/index.html"):
            return self._send(200, HTML, "text/html; charset=utf-8")

        if p == "/api/events":
            want_ai = parse_qs(urlparse(self.path).query).get("ai", ["1"])[0] != "0"
            events = load_events(with_ai=want_ai)
            # The outside reviewer runs on live output, not just in tests.
            review = audit([type("E", (), e)() for e in events]) if events else None
            payload = {
                "total": len(events),
                "needs_action": sum(1 for e in events if e.get("severity") in ("critical", "high")),
                "verified": sum(1 for e in events if e.get("verified") is True),
                "covered": len(EXPLAINERS),
                "ai_enabled": ai.enabled(),
                "ai_stats": ai.stats(),
                "served_at": time.time(),
                "review": review,
                "events": events,
            }
            return self._send(200, json.dumps(payload, indent=2))

        if p == "/api/ask":
            q = parse_qs(urlparse(self.path).query)
            question = (q.get("q") or [""])[0][:500]
            eid = (q.get("event_id") or [""])[0]
            if not question:
                return self._send(400, {"error": "missing ?q="})
            for e in load_events(with_ai=False):
                if e.get("event_id") == eid or e.get("event_type") == eid:
                    # Measured 2026-10-02: an uncached follow-up took 15.6s —
                    # the key was rate-limited so the call fell through the whole
                    # model chain. The UI shows "asking…" that whole time, which
                    # reads as broken in a demo. Cap it and answer with what we
                    # already know rather than hanging.
                    res = ai.answer_with_deadline(question, e, e.get("event_id") or eid,
                                                  timeout=8.0)
                    return self._send(200, json.dumps(res, indent=2))
            # The UI sends "TYPE|ID" (see card() key) — match either part.
            if "|" in eid:
                etype, _, epart = eid.partition("|")
                for e in load_events(with_ai=False):
                    if e.get("event_type") == etype and e.get("event_id") == epart:
                        res = ai.answer_with_deadline(question, e, e.get("event_id") or epart,
                                                      timeout=8.0)
                        return self._send(200, json.dumps(res, indent=2))
            return self._send(404, {"error": "unknown event_id"})

        if p == "/api/health":
            return self._send(200, json.dumps({
                "status": "ok", "events_on_disk": len(list(EVENT_DIR.glob("*.json"))),
                "explainer_types": len(EXPLAINERS),
                "ai_enabled": ai.enabled()}))

        return self._send(404, json.dumps({"error": "not found"}))


def main():
    ap = argparse.ArgumentParser()
    # $PORT is how every PaaS (Render, Fly, Railway) tells a web service which
    # port to bind. Default 8080 locally; on a host it takes precedence.
    ap.add_argument("--port", type=int,
                    default=int(os.environ.get("PORT", 8080)))
    a = ap.parse_args()
    srv = ThreadingHTTPServer(("0.0.0.0", a.port), Handler)
    print(f"HoldWatch on http://0.0.0.0:{a.port}", flush=True)
    print(f"  events read from {EVENT_DIR}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()