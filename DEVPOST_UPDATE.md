# Devpost update — what to change, exactly

Three things on the submission are out of date, now that the site is live at
https://holdwatch-site.onrender.com. Everything else is correct.

---

## 1. "Try it out" links — add the site first

**Currently on the page:** `ethics-theater-duty-jackie.trycloudflare.com`

I initially wrote that this link was dead. **That was wrong — I checked instead of
assuming and it returns 200.** It is still serving, because the cloudflared process
for it is still running on the VPS.

But it is still the wrong link to publish, for two reasons:

1. **It is a quick tunnel.** The hostname is bound to a running process and changes
   on every restart, so the link silently rots. Judges who bookmark it, or who
   click after a reboot, get nothing.
2. **It serves a stale instance.** That endpoint returns `ai_enabled: false` — the
   old manually-started process, not the systemd one. A judge clicking it today
   would see the AI layer missing.

Use these four, in this order:

```
https://holdwatch-site.onrender.com
https://holdwatch-dashboard.onrender.com
https://holdwatch-receiver.onrender.com
https://github.com/HusseinAdeiza/holdwatch
https://youtu.be/bFOglGDKJpM
```

Labels: *Product site* · *Live dashboard* · *Webhook receiver* · *GitHub Repo* · *youtu.be*

---

## 2. "Working demo URL" field

**Currently:** the same tunnel URL.

```
https://holdwatch-dashboard.onrender.com
```

---

## 3. "Testing instructions or credentials" field

The current text describes the tunnel and says the repository is the durable
artefact. Replace the body with:

```
The hosted demo above is the fastest way to judge this — it is a live deployment
of this exact repository, serving 7 real captured PayPal events, all
signature-verified, including a completed USD 4,200.00 sandbox checkout. Cards are
ordered by severity, so a live hold appears first. The "Ask a follow-up" button
works on every card and answers from that event's own verified fields.

The webhook receiver is deployed too. Posting a forged payload to it returns
HTTP 400 {"error": "signature verification failed"}, so the verification path is
demonstrable rather than asserted. It fails closed: an event is only recorded
when PayPal has confirmed that specific signature.

Both run on a paid instance and stay up, so there is no cold start. The
repository is the durable artefact and has no such dependency.

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

## Leave these alone — already correct

- Gallery images and captions (all four paired correctly)
- Embedded video
- Project story, elevator pitch, 13 tags
- Technology-requirement and experience-rating fields

---

## Optional but worth it: post an Update

Devpost shows project Updates to your followers, and it is the only part judges
see change during the competition. Suggested text:

> **Live demo now deployed, and it fails closed on forged events.**
>
> The dashboard is up at holdwatch-dashboard.onrender.com serving 7 real
> signature-verified PayPal events, including a completed $4,200.00 sandbox
> checkout.
>
> The interesting part was getting the webhook receiver wrong twice. It originally
> skipped signature verification when no webhook id was configured — which meant
> a deployed instance would accept a forged "your payout was held" and render it
> as fact. Fixing it once wasn't enough either, because the deployed service was
> still running the older commit.
>
> The rule now is simple: an event is recorded only when PayPal has confirmed
> that exact signature. Everything else is rejected. Posting a forgery to the live
> receiver returns HTTP 400.
>
> Repo and video in the description.

---

## After you edit

Run the check that matters:

```bash
cd /root/web3alphatester/paypal && bash verify_all.sh
```

It re-tests the demo URL, both rejection paths on both receivers, and every
submission artefact — 31 checks. If Devpost shows a URL that 404s, it will catch it.
