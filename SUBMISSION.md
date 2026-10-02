# PayPal AI Hackathon — submission copy

Paste-ready. Every claim below is something we ran and verified.

- **Video:** https://youtu.be/bFOglGDKJpM
- **Repo:** https://github.com/HusseinAdeiza/holdwatch
- **Deadline:** Nov 12, 2026, 2:00 PM PT

---

## 1. Tagline (the one-liner judges read first)

> **HoldWatch reads PayPal's restriction events and tells you what happened to your
> money — in plain language, with the evidence — and says "cause not disclosed"
> rather than inventing one.**

---

## 2. Project description

HoldWatch is a webhook monitor for the PayPal events that move money. When a payout
is held, blocked, failed or disputed, PayPal emits an event and leaves you to work
out what it means. HoldWatch verifies that event against PayPal's own signature
API, resolves it to the full PayPal record, and returns three things: what
happened, what is actually known, and what to do next.

**It detects and explains. It does not predict.** That distinction is deliberate
and we would rather state it than overclaim — see Limitations.

### What it does

- **Receives and verifies.** A signature-checked webhook receiver. Every event is
  verified against `POST /v1/notifications/verify-webhook-signature` — PayPal's
  endpoint, not our own arithmetic. A local CRC32 was implemented first and
  discarded: it failed against every genuine event, and being symmetric it would
  also have let anyone who saw one valid triple forge others.
- **Rejects forgeries at intake.** A payload that fails verification is dropped
  with `HTTP 400` and never rendered. Verified by negative control.
- **Collapses re-deliveries.** PayPal retries delivery up to 25 times over three
  days. Events are deduplicated on `transmission_id + event_type`, because
  `simulate-event` reuses a single event id across types and that collapsed five
  distinct events into one row in our first build.
- **Explains 19 event types** with an impact statement and a ranked action list,
  produced deterministically so the same input always gives the same output.
- **Resolves state PayPal never webhooks.** One capture completed
  (`GET /v2/payments/captures/` returns 200) but **no webhook was delivered** for
  it. HoldWatch asks PayPal for the current record when a payload carries an id.
  A monitor that only listens is incomplete.
- **Adds AI where it earns its place, and nowhere else.** The model tailors the
  explanation to the actual amount and recipient, covers event types outside the
  rule set, and answers follow-ups grounded in verified facts.

### The part we care about most

**Only 1 of our 19 explanations states a known cause.** For the other 18, PayPal
does not disclose a reason in the payload. So the interface says:

> **CAUSE UNKNOWN** — *"PayPal does not disclose the reason in this event. We will
> not invent one."*

An invented reason sends someone to the wrong remedy. Every model response is
re-checked after generation, and any text asserting an unverified cause is
discarded — verified across 6 live outputs, 0 violations.

---

## 3. Verified against a real transaction

A real PayPal checkout completed in the sandbox on 2026-10-02 and produced this
project's first genuinely-signed event:

```
order       52A89694AB3486153
amount      USD 4,200.00
capture     6YH19408NM0071141
event       CHECKOUT.ORDER.APPROVED
signature   verify-webhook-signature -> SUCCESS
```

Two defects surfaced only because of a real transaction, and both are fixed:

1. **Order payloads have a different shape.** `CHECKOUT.ORDER.*` nests everything
   under `purchase_units[0]`; payout events do not. The original extractor read
   only the payout shape, so a genuine $4,200 approval rendered with **no amount
   at all**.
2. **Some PayPal state changes never arrive as webhooks** — hence the API
   resolution step above.

---

## 4. Tools used

| | |
|---|---|
| **PayPal** | REST API v2 — Orders, Invoicing, Webhooks; `verify-webhook-signature`; OAuth 2.0 client-credentials |
| **AI** | Google Gemini (`gemini-3-flash-preview`), optional, via `GEMINI_API_KEY` |
| **Language** | Python 3 standard library only — no framework, no dependencies to install |
| **Frontend** | Vanilla HTML/CSS/JS served by the standard library |

**PayPal is central**: the event stream is the product's only input, and every
figure shown comes from PayPal's API or a PayPal-signed payload.

**The AI is genuinely optional.** With no API key set, all cards still render from
the deterministic rule engine — verified with the environment variable unset.
`ai.py` never raises into the product.

---

## 5. Running it

```bash
mkdir -p ~/.config/paypal
echo -n 'YOUR_CLIENT_ID'     > ~/.config/paypal/client_id      && chmod 600 ~/.config/paypal/client_id
echo -n 'YOUR_CLIENT_SECRET' > ~/.config/paypal/sandbox_secret && chmod 600 ~/.config/paypal/sandbox_secret

export GEMINI_API_KEY=...        # optional

python3 receiver.py --port 8099        # webhook intake — needs a public HTTPS URL
python3 register_webhook.py https://your-endpoint   # subscription is API-only
python3 app.py --port 8080            # dashboard
```

Dependencies: **none.** The Python standard library.

**Note on setup:** PayPal's developer dashboard does not expose webhook
registration in its UI. `register_webhook.py` uses the documented API instead.
PayPal also has no update verb for webhooks — `PUT` returns 404 and re-POSTing an
existing URL returns `WEBHOOK_URL_ALREADY_EXISTS` — so re-registration is
delete-then-create.

---

## 6. Limitations

Stated here rather than under questioning.

1. **We detect and explain; we do not predict.** Predicting a hold needs
   transaction history, and PayPal gates `/v1/reporting/*` behind partner status:
   `403 NOT_AUTHORIZED` on a standard sandbox app. We tried it, measured the
   response, and rebuilt on the event stream.
2. **Payouts is not enabled on our app** (`404`), so a genuine payout flow has
   not been exercised end to end.
3. **Test events come from `simulate-event`**, which replays PayPal's documented
   sample. Those events are genuinely signed by PayPal and verified by its API,
   but they are generated rather than arising from organic account activity. The
   `$4,200` order above is a real completed checkout, not a simulation.
4. **The evaluation set is synthetic and the ground truth is ours, not PayPal's.**
   `scenarios.py` scores the original rule engine on 20 scenarios — recall 0.80,
   precision 1.00, zero false positives. That measures whether our rules
   discriminate between known shapes. PayPal's hold decisions are not public, so
   no ground-truth dataset exists for anyone. Details in `EVAL_LOG.md`.
5. **MIT licensed.** Not affiliated with PayPal.

---

## 7. Judging criteria → evidence

| Criterion | Where to look |
|---|---|
| **Technological Implementation** | Signature verification against PayPal's API, forgery rejection at intake, replay-safe dedup, deterministic explanation engine, plus a scoped optional AI layer |
| **Design** | Severity-ordered dashboard, labelled fields before prose, raw payload one click deep, an outside reviewer that audits our own output on live data |
| **Potential Impact** | Named persona: a freelancer or exporter whose PayPal funds are frozen with no stated reason and no next step |
| **Innovation / Idea** | The differentiator is the refusal — a payments monitor that reports what it does not know, and screens a language model to keep it honest |
| **Presentation** | 77-second video: persona → real $4,200 payment → signature verification → "cause not disclosed" → the honest limitation |
