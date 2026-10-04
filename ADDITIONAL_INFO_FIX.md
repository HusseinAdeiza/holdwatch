# Additional info — one correction

Everything on this screen is verified accurate except **one sentence**. Fix that
one, save, and this screen is done.

---

## ❌ The false claim

Current text:

> **Both run on a paid instance and stay up, so there is no cold start.**

**Only the dashboard is on a paid instance.** The receiver is deliberately on
Render's **free** tier — PayPal retries delivery 25 times over 3 days, so a
sleeping receiver delays an event but never loses one.

A judge who spots this learns two things: the write-up wasn't checked, and the
author doesn't know their own deployment. It's the only unverified claim on the
page.

---

## ✅ Replacement text — paste over the current block

```
The hosted demo above is the fastest way to judge this — it is a live deployment
of this exact repository, serving 7 real captured PayPal events, all
signature-verified, including a completed USD 4,200.00 sandbox checkout. Cards are
ordered by severity, so a live hold appears first. The "Ask a follow-up" button
works on every card and answers from that event's own verified fields.

The webhook receiver is deployed too, and it has a landing page at its root: press
the button and it POSTs a forgery to itself, returning HTTP 400
{"error": "signature verification failed"}. The verification path is demonstrable
rather than asserted. It fails closed — an event is recorded only when PayPal has
confirmed that exact signature.

The dashboard runs on a paid instance and stays up, so there is no cold start on
the link above. The receiver is on a free tier deliberately: PayPal retries
delivery 25 times over 3 days, so a sleeping receiver delays an event but never
loses one.

For offline verification with no credentials, a genuine PayPal-signed payload is
committed at fixtures/sample_payout_held.json:
  python3 explainer.py fixtures/sample_payout_held.json
  python3 scenarios.py --run            # reproduce the published figures
  python3 hold_signals.py --self-test

To run against your own PayPal sandbox, create a free REST app at
developer.paypal.com and set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET (env vars
or ~/.config/paypal/). GEMINI_API_KEY is optional — with no key the dashboard
renders entirely from the deterministic rule engine.
```

---

## Two small upgrades folded in

- **Product site URL added** — it's your best single artefact and it wasn't listed
  anywhere on this screen.
- **Receiver landing page** now described accurately. It didn't exist when this
  text was written; a judge who opens the root gets a working forgery test rather
  than `{"error": "not found"}`.

---

## Everything else on this screen — verified, leave alone

| Field | Check |
|---|---|
| Technology requirement | All 6 PayPal tools named with endpoints; Gemini named with its 3 jobs; the 403 finding included |
| Sponsor tools | "None, used other AI tools" — correct, we used neither |
| Repository URL | 200, MIT licence visible |
| Demo URL | 200, 0.62s, 7 events verified |
| Experience rating | 9 with specific, non-generic justification |
| Feedback text | The undocumented quirks are genuinely useful; keep it |
| Country / submitter | Nigeria / Individual — correct |
| Three confirmations | Checked |

The feedback paragraph is unusually strong — naming `billing_info`,
`WEBHOOK_URL_ALREADY_EXISTS` and the missing capture webhook reads like someone
who actually integrated this. PayPal's judges will recognise that.

---

## Then

**Project overview** → elevator pitch + new thumbnail.
**Project details** → the corrected story.

After this, the only remaining item is the video swap on the video field.
