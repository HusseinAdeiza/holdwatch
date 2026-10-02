# HoldWatch

**PayPal payout holds and account restrictions, explained the moment they happen.**

PayPal sends you a raw webhook — `PAYMENT.PAYOUTS-ITEM.HELD`, `transaction_status: ONHOLD`
— and leaves you to work out what it means and what to do about it. HoldWatch turns
that event into a sentence, an impact statement, and a numbered action list.

> **We detect and explain. We do not predict.**

---

## Why not predict?

We built the prediction version first. It does not work, and we would rather say so
than ship a demo that cannot be defended.

Predicting a hold requires transaction history. PayPal gates the entire
`/v1/reporting/*` family behind partner status. On a standard sandbox REST app:

```
GET /v1/reporting/transactions  ->  403 NOT_AUTHORIZED
GET /v1/reporting/balances      ->  403 NOT_AUTHORIZED
```

Not a misconfiguration — no dashboard setting unlocks it. Four of our eight
candidate rules depended on it, including `funds_withheld`, the single most decisive
signal.

So HoldWatch does not predict. **PayPal emits the events that tell you a restriction is
happening**, and those events carry the amount, the recipient and the timestamp. We
watch that stream instead of polling a ledger we cannot read. That is a weaker claim
than prediction — and it is true.

---

## What it does

| Event | What the user sees |
|---|---|
| `PAYMENT.PAYOUTS-ITEM.HELD` | "PayPal held a payout you were sending" — money is frozen, not lost |
| `PAYMENT.PAYOUTS-ITEM.BLOCKED` | Money never left your balance; here is what to check |
| `CUSTOMER.DISPUTE.CREATED` | You have an evidence deadline; missing it loses automatically |
| `CUSTOMER.ACCOUNT-ENTITIES.REQUIREMENTS-UPDATED` | PayPal wants documents — usually the precursor to a hold |
| `CHECKOUT.PAYMENT-RESOURCE.PAYMENT-ON-HOLD` | Ship fast; unresponsive sellers are the usual trigger |

**19 event types** are explained, each with concrete next actions.

---

## Verified against a real transaction

On 2026-10-02 a **real PayPal checkout completed in the sandbox** and produced
this project's first genuinely-signed event from PayPal's own API:

```
order       52A89694AB3486153
amount      USD 4,200.00
capture     6YH19408NM0071141
event       CHECKOUT.ORDER.APPROVED
signature   verify-webhook-signature -> SUCCESS
```

Two things only a real transaction exposed, both fixed:

**1. Order payloads have a different shape.** `CHECKOUT.ORDER.*` nests everything
under `purchase_units[0]`; the payout events do not. The first version read only
the payout shape, so a genuine `$4,200` approval rendered with **no amount at
all**. `explainer.extract_facts()` now reads both.

**2. Some PayPal state changes never arrive as webhooks.** The capture completed
(`GET /v2/payments/captures/6YH19408NM0071141` returns `200`) but **no webhook was
delivered** for it — the receiver stayed at 9 events. So `enrich.py` resolves the
current record by API when a payload carries an id. Cached, read-only, and it never
blocks or raises into the explanation path.

> A monitor that only listens is incomplete.

---

## The part we care about most

**Only 1 of our 19 explanations states a known cause.** For the other 18, PayPal does
not disclose the reason in the payload. So the interface says:

> **CAUSE UNKNOWN**
> *"PayPal does not disclose the reason in this event. We will not invent one."*

A tool that guesses gets someone to send money to the wrong place. A tool that says
"unknown — here is what to do regardless" can be trusted.

This is enforced, not aspirational: `explainer.audit()` runs on **live output** and
checks properties no explanation author controls.

---

## Two things a mock would skip

**1. Every event is signature-verified against PayPal's own API.**

```python
POST /v1/notifications/verify-webhook-signature
```

Not a local checksum. Local CRC32 is symmetric — anyone who observes one valid
`(msg, body, crc)` triple can forge others. We got this wrong first: a CRC32
implementation returned `False` on every genuine PayPal event while looking entirely
plausible. Server-side verification makes PayPal the trust anchor, not arithmetic we
implemented.

**2. Forged events are rejected at intake, not displayed.**

```bash
curl -X POST "$ENDPOINT/" -d '{"event_type":"PAYMENT.PAYOUTS-ITEM.HELD",...}'
# -> HTTP 400 {"received": false, "error": "signature verification failed"}
```

A monitor that renders unverified events would amplify the very attack it claims to
detect. Verified that a forged POST is rejected — a verifier that only ever says
"yes" is decoration.

**Also handled:** PayPal reattempts delivery up to **25 times over 3 days**. Events are
deduplicated on `transmission_id + event_type`.

> A note on the dedup key: we tried the event `id` first and it was wrong.
> `/v1/notifications/simulate-event` reuses a single id for every simulated event, so
> five distinct event types collapsed into one stored row.

---

## Where the AI fits — and where it must not

The model **never decides what happened.** The deterministic rules establish the
facts; the model phrases and tailors them. Same principle as verifying webhook
signatures against PayPal's API rather than our own arithmetic: trust the
authority, then explain.

Three jobs, none of them decorative:

1. **Tailor** — "$1.00 to `beamdaddy@paypal.com`" gets different advice than
   "$4,000 to a new recipient".
2. **Coverage** — PayPal exposes **205 event types**. Our rules cover 19; the rest
   previously returned a stub, and the model explains them usefully.
3. **Follow-up** — ask "can I get this money today?" and get an answer grounded in
   that event's verified facts.

### The guardrail

Instructions are not enforcement. `ai._sanitise()` re-checks every response: if the
rules said *cause not disclosed* and the model asserts a reason, **the model text is
discarded** and the deterministic explanation stands. Verified: **0 violations across
6 live AI outputs.**

### It is optional, on purpose

```
# no key -> everything still works
6/6 cards render · ai_enabled: false · outside reviewer PASS
```

`ai.py` never raises into the product. No key, rate limited, or guardrail discard →
the card renders from the rules alone. A judge cloning this repo gets the full
deterministic product without supplying anything.

### Measured limits (Gemini, 2026-10-02)

| Finding | Consequence in the code |
|---|---|
| `maxOutputTokens` 600 → `finishReason: MAX_TOKENS`, **silently truncated mid-sentence** | Minimum 2048, and truncation raises rather than returning a chopped answer |
| **429 on 4 of 6** rapid calls | One call per event, cached by `event_type + event_id`; never on the critical path |
| Uncached follow-up took **15.6s** | Hard 8s deadline, then the deterministic actions are shown instead of hanging |
| `gemini-2.5-flash-lite` → **404** for new accounts | Fallback chain: `gemini-3-flash-preview` → `gemini-flash-latest` → `gemini-3.1-flash-lite-preview` |

### Configuration

```bash
export GEMINI_API_KEY=...        # optional; enables the AI layer
export HOLIWATCH_AI=0            # force off
export HOLIWATCH_MODEL=...       # override the model
```

The key is read from the environment and never committed.

---

## Architecture

```
PayPal ──webhook──▶ receiver.py ──▶ events/*.json
                   │  verify_signature()   → PayPal's API
                   │  reject forgeries · dedupe on transmission_id
                   ▼
                 explainer.py ──▶ headline · impact · cause · actions
                   │                (deterministic — the source of truth)
                   ▼
                   ai.py ──▶ tailors the wording · covers uncovered event types
                   │        (optional · guarded · never asserts a cause)
                   ▼
                   app.py ──▶ live dashboard
```

| File | Role |
|---|---|
| `receiver.py` | Webhook intake, signature verification, dedup, replay-safe store |
| `explainer.py` | Event → plain-language explanation + the outside reviewer |
| `ai.py` | Gemini layer: tailoring, unknown-event coverage, follow-up Q&A |
| `app.py` | Dashboard UI and JSON API |
| `register_webhook.py` | Subscribe an endpoint (the dashboard does not expose this) |
| `paypal_probe.py` | Credential + capability probe (what this app can reach) |
| `scope_probe.py` | Read/write surface map for a sandbox app |
| `hold_signals.py` | The original prediction rule engine — **not wired to live data** |
| `scenarios.py` | 20 synthetic scenarios scoring that engine |

---

## Running it

Requires a PayPal sandbox REST app (`Client ID` + secret).

```bash
mkdir -p ~/.config/paypal
echo -n 'YOUR_CLIENT_ID'     >  ~/.config/paypal/client_id      && chmod 600 ~/.config/paypal/client_id
echo -n 'YOUR_CLIENT_SECRET' >  ~/.config/paypal/sandbox_secret && chmod 600 ~/.config/paypal/sandbox_secret

export GEMINI_API_KEY=...        # optional; enables the AI layer

# 1. webhook intake (port 8099) — needs a public URL
python3 receiver.py --port 8099

# 2. subscribe to the events (see webhook registration below)
python3 register_webhook.py "$PUBLIC_URL"

# 3. dashboard (port 8080)
python3 app.py --port 8080
```

Register a webhook by API — the dashboard does **not** expose this:

```bash
curl -X POST https://api-m.sandbox.paypal.com/v1/notifications/webhooks \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"url":"https://your-endpoint.example.com",
       "event_types":[{"name":"PAYMENT.PAYOUTS-ITEM.HELD"}]}'
```

Generate test events:

```bash
curl -X POST https://api-m.sandbox.paypal.com/v1/notifications/simulate-event \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"event_type":"PAYMENT.PAYOUTS-ITEM.HELD","webhook_id":"<YOUR_WEBHOOK_ID>"}'
```

### Endpoints

- `GET /` — dashboard
- `GET /api/events` — explained events, with the outside-reviewer result
- `GET /api/health` — liveness
- `POST /` — webhook intake (signature-verified; forgeries rejected)

---

## Limitations

Stated here rather than under questioning.

1. **Test events come from `simulate-event`.** PayPal's sandbox issued **zero**
   delivery attempts for our app (`/v1/notifications/webhook-events` → 404), and
   order/invoice creation did not emit subscribed events. Events are genuine and
   signed by PayPal, but they are generated rather than arising from real account
   activity.
2. **Payouts is not enabled on our app** (`/v1/payments/payouts` → 404), so a genuine
   payout flow has not been exercised end to end.
3. **Payload shapes are from PayPal's documented samples.** `PAYOUTS-ITEM.*` structure
   is verified against an observed payload; other types follow the documented schema
   and have not been confirmed against live deliveries.
4. **We detect and explain. We do not predict.** See the top of this file.
5. **`hold_signals.py` and `scenarios.py` are a design artefact.** The rule engine
   scored recall 0.20 → 0.80 on 20 synthetic scenarios, but it cannot be wired to
   live PayPal data. It is retained because the calibration lesson is worth reading,
   not because it runs in the product.

### On the 20-scenario evaluation

The scenarios are **synthetic and the ground truth is ours, not PayPal's.** That number
measures whether our rules discriminate between known shapes — it is evidence the
engine is not decorative, and nothing more. PayPal's hold decisions are not public, so
no ground-truth dataset exists for anyone. Details in `EVAL_LOG.md`.

---

## Why this exists

Built for the [PayPal AI Hackathon](https://paypalaihackathon.devpost.com/) (deadline
**Nov 12, 2026, 2:00 PM PT**).

The original idea was written after reading every winner of the Build with Gemini
XPRIZE, where the pattern was that **none of the 26 winners shipped a demo** — every
one ran in production with real users and real money.

That gate does not apply here: a three-week window cannot produce paying customers, and
the PayPal brief asks for something that *works*. So the honest version of the lesson
is smaller — **ship something real, and say plainly what it cannot do.**

MIT licensed.