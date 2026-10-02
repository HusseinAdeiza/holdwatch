# Inspiration

Someone close to me got paid for real work, and the money never arrived.

Not lost in transit, not a failed transfer — **frozen**. PayPal's API had done
everything it was supposed to do. The payment was authorised, the sender was
verified, the funds moved. And then the account was restricted, with no stated
reason and no suggested next step.

What made it worse wasn't the freeze. It was the silence. The API the merchant
*already had* was reporting a status, clearly, in machine-readable form — and
turning that into *"here is what happened to your money, here is what is actually
known, and here is what to do"* was manual work every merchant has to invent
again from scratch.

So HoldWatch watches that stream and does the translation. Nothing more clever
than that, on purpose.

---

# What it does

A receiver, an explanation engine, and a dashboard.

| Stage | Behaviour |
|---|---|
| **Receive** | Signature-verified webhook intake. Failures are rejected at the door. |
| **Verify** | Every event checked against `POST /v1/notifications/verify-webhook-signature` — PayPal's endpoint, not our arithmetic. |
| **Deduplicate** | Keyed on `transmission_id + event_type`. PayPal re-delivers up to 25 times over 3 days. |
| **Explain** | 19 event types → impact statement + ranked actions, deterministically. |
| **Enrich** | Resolve the live PayPal record for events whose full state never got webhooked. |
| **Tailor** *(optional)* | A language model phrases it for the actual amount and recipient, and answers follow-ups. |

---

# The decision that shaped the project

The original plan was to **predict** holds. You cannot. Predicting requires
transaction history, and PayPal gates the whole `/v1/reporting/*` family behind
partner status:

```
GET /v1/reporting/transactions   →  403 NOT_AUTHORIZED
GET /v1/reporting/balances       →  403 NOT_AUTHORIZED
```

That's not a misconfiguration. No dashboard setting opens it.

So the product changed to **detect and explain** — a weaker claim, and one we can
actually stand behind. PayPal emits the events that signal a restriction; we read
those instead of polling a ledger we can't read.

I've put that limitation in the README rather than hoping nobody asks, because
the honest version is more useful than the impressive one.

---

# The part I'd point a judge at

**Only 1 of our 19 explanations states a known cause.** For the other 18, PayPal
doesn't disclose a reason in the payload. So the interface says:

> **CAUSE UNKNOWN** — *"PayPal does not disclose the reason in this event. We will
> not invent one."*

An invented reason sends someone to the wrong remedy — chasing a fraud review
when the real cause was an address mismatch.

And this holds against the language model too. Instructions aren't enforcement,
so every generated response is re-screened and any text asserting an unverified
cause is **discarded**. Verified across 6 live outputs: 0 violations.

---

# What I learned building it

**A verifier that always says yes is decoration.** My first signature check was a
local CRC32. It looked plausible and failed against *every* genuine PayPal event.
Worse, CRC32 is symmetric — anyone who observed one valid `(msg, body, crc)`
triple could forge others. Moving verification server-side made PayPal the trust
anchor instead of arithmetic I'd written.

**Two bugs that only a real transaction could reveal.** After a genuine $4,200
checkout completed:

1. The card rendered with **no amount**. `CHECKOUT.ORDER.*` nests everything under
   `purchase_units[0]`; my extractor only understood the payout shape. The
   headline was right and the number was missing — which is the kind of bug that
   looks fine until a judge notices.
2. The capture completed (`GET /v2/payments/captures/` → `200`) and **no webhook
   was ever delivered** for it. So the product now asks PayPal for current state
   when an event carries an id. A monitor that only listens is incomplete.

**Small API details that cost real time.** The `201` response to invoice creation
is a links-only body with no `id`. A recipient email must nest under
`billing_info` or it is silently dropped. Webhook registration isn't in PayPal's
dashboard at all, and there's no update verb — `PUT` returns `404`, re-POSTing a
taken URL returns `WEBHOOK_URL_ALREADY_EXISTS`, so re-registration is
delete-then-create.

---

# Challenges

**Being honest about scope.** I built a rule engine, scored it on 20 synthetic
scenarios, and it started at **0.20 recall** — it could not cry wolf. Two
calibration rounds took it to **0.80 recall at 1.00 precision**, with zero false
positives held throughout. I deliberately stopped at 0.80 rather than tune to
1.00, because a number arrived at by tuning tells you nothing.

That set is **synthetic, and the ground truth is mine, not PayPal's.** It shows the
engine discriminates between known shapes — nothing more. PayPal's hold decisions
aren't public, so no ground-truth dataset exists for anyone.

**Making AI optional.** With no API key set, every card still renders from the
deterministic engine. I verified that with the environment variable unset, because
a submission that dies without an API key is a demo, not a product.

**Rate limits shaped the architecture.** The key returned `429` on 4 of 6 rapid
calls, and an uncached follow-up took 15.6 seconds. So: one call per event, cached
by type and id, never on the request path, and a hard 8-second deadline that
falls back to deterministic actions rather than a spinner.

---

# Try it yourself

```bash
python3 receiver.py --port 8099     # needs a public HTTPS URL
python3 register_webhook.py https://your-endpoint
python3 app.py --port 8080         # dashboard
```

Python standard library only. No dependencies, no framework. `GEMINI_API_KEY` is
optional.

MIT licensed. Not affiliated with PayPal.
