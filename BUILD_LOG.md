# HoldWatch — build log

PayPal AI Hackathon · deadline **Nov 12, 2:00 PM PT** · started 2026-10-02

---

## The thesis, and how it changed

**Original:** *"PayPal froze $4,000 of my money and told me nothing. I built the agent that
reads your transaction history and tells you what to fix before it happens."*

**Killed by the probe, not by opinion.** `/v1/reporting/transactions` → `403
NOT_AUTHORIZED`. PayPal gates the entire `/v1/reporting/*` family behind partner
status; no dashboard setting unlocks it. Four of the eight rules depended on it,
including `funds_withheld` — the single most decisive signal.

Rather than build rules against invoice metadata and call it payment-risk
detection (a demo that runs and a claim we cannot defend — playbook A4), the
product pivoted:

> **"PayPal held your payout and told you afterwards. We catch it in the stream,
> tell you which signal fired, what it means, and what to do."**

Weaker than prediction, and **true**. Overclaiming was never an option here.

---

## Verified working (real API responses, 2026-10-02)

| Component | Evidence |
|---|---|
| Sandbox credentials | `AUTH OK` — token issued |
| Webhook registration | `HTTP 201`, id `6X44828325248143E`, **18 event types** |
| Registration method | `POST /v1/notifications/webhooks` — **the dashboard does not expose this** |
| Public endpoints | both tunnels reachable; UI verified in a real browser |
| **Real signed events** | 6 delivered, `verification_status == SUCCESS` |
| **Forged events** | rejected, `HTTP 400` |
| Orders / Invoices | `HTTP 201` on create |
| Outside reviewer | `PASS` on live output, 19/19 event types |

**Live:** https://ethics-theater-duty-jackie.trycloudflare.com
(receiver: `submitting-jpg-really-musician.trycloudflare.com`)

---

## Bugs found and fixed — all real, all caught by testing

1. **CRC32 verification returned False on every genuine event.** The local
   shortcut looked plausible and was simply wrong. Switched to PayPal's
   `verify-webhook-signature` (method 2). Beyond correctness: local CRC32 is
   *symmetric*, so one observed valid triple enables forgery. Server-side
   verification makes PayPal the trust anchor.
2. **Forged events were recorded and displayed.** Anyone could POST a fake
   "payout held" and drive our own UI — the monitor would amplify the attack it
   claims to detect. Now rejected at intake (`HTTP 400`).
3. **`dedup_key` used the event id.** PayPal's `simulate-event` reuses one id
   for every simulated event, so 5 distinct event types collapsed into 1 stored
   row. Keyed on `transmission_id + event_type` instead.
4. **`Explanation` carried no `severity`/`verified`.** Every card would have
   rendered grey with no verification badge. Caught by reading the actual API
   response, not by assuming.
5. **Two `NameError`s** — missing `import urllib` and undefined `BASE`. Caught
   by importing the module standalone before restarting the service.
6. **The outside reviewer had a false positive.** It flagged `confirmed` +
   `cause=None` as an unverified claim, but for `PAYOUTS-ITEM.SUCCEEDED` the
   event *itself* is the confirmation. Fixed the checker, not the data.

---

## Architecture

```
PayPal ──webhook──▶ receiver.py ──▶ events/*.json
                    │ verify_signature (PayPal API)
                    │ reject forgeries · dedupe by transmission_id
                    ▼
              explainer.py ──▶ headline · impact · cause · actions
                    │
                    ▼
                  app.py ──▶ live dashboard (public URL)
```

`explainer.audit()` runs on **live output**, not just in tests — it checks
properties no explanation author controls: duplicate emissions, missing actions,
and confidence claims not backed by the event.

---

## The design decision that matters

**Only 1 of 19 explanations states a known cause.** For 18 of them, PayPal does
not disclose the reason in the payload. So the UI says:

> **CAUSE UNKNOWN** — *"PayPal does not disclose the reason in this event. We will not invent one."*

This is the honest core of the product. A tool that guesses gets someone to send
money to the wrong place. A tool that says "unknown, here is what to do
regardless" is trustworthy — and it is the outside reviewer (rule 10) applied to
our own output.

---

## Limitations — publish these unprompted

1. **All test events are from `simulate-event`.** PayPal's own sandbox did not
   emit subscribed events for our app (`/v1/notifications/webhook-events` → 404,
   zero delivery attempts).
2. **Payouts are not enabled on this app** (`/v1/payments/payouts` → 404), so a
   genuine payout flow has not been exercised end to end.
3. **Event payload shapes are from PayPal's documented samples.** Verified
   structure for `PAYOUTS-ITEM.*`; other types are inferred from the documented
   schema, not from observed live payloads.
4. **We detect and explain. We do not predict.** Anyone claiming this predicts
   holds would need data we proved is partner-gated.
5. The original 8-rule engine and its 20-scenario eval (`hold_signals.py`,
   `scenarios.py`, recall 0.20 → 0.80) remain valid **as a design artefact** but
   cannot be wired to live data. Kept, not deleted — the calibration lesson
   stands.

---

## Next

- [ ] Public repo + README (OSS licence detectable at top — rules requirement)
- [ ] Explainer Cut demo video, **< 3 minutes**, public YouTube
- [ ] Permanent deployment (quick tunnels are ephemeral)
- [ ] Ask PayPal to enable Payouts, to exercise a true payout flow
- [ ] Re-check `Life After Code` rules (GitLab, $45k, 191 regs) — it beats
      PayPal on odds if the rules land clean