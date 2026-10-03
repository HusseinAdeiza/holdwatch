# DEPLOY

**Status: live, $0/month, nothing at risk.**

---

## What judges click

| | URL | Why this one |
|---|---|---|
| **Dashboard** | `https://holdwatch-dashboard.onrender.com` | **Permanent.** Never changes. Keep-warmed so it never cold-starts. |
| **Receiver** | `https://holdwatch-receiver.onrender.com` | The webhook intake. Public so the 400 rejection is demonstrable. |

Both are stable DNS names that survive reboots and redeploys.

---

## Why not the VPS tunnels

The VPS also runs the app (faster, auto-restarts, fails closed on forgeries), but
it is exposed through **quick tunnels**, which generate a random hostname that
**changes on every restart**. A quick-tunnel URL in the submission is a link that
dies on the next reboot — worse than a slow page.

`sanitovaehs.com` is the Sanitova EHS company site with live email and webmail on
Truehost nameservers. Moving it to Cloudflare would risk all of that for a
hackathon link. Not worth it. **A separate domain would be the safe way to get a
custom hostname.**

---

## Keeping Render awake — free

Render's free tier spins down after ~15 min idle; the documented worst-case wake is
~50s. A systemd timer on the VPS pings both services every 8 minutes:

```bash
systemctl list-timers render-keepalive.timer
systemctl status render-keepalive.service
sudo systemctl start render-keepalive.service    # force a ping now
```

Runs from the always-on VPS, so it needs no schedule on Render's side and costs
nothing. Measured warm response: **~0.5–0.9s**.

---

## Layout

**VPS** (`75.119.152.168`) — systemd, enabled on boot:

| Unit | Port | Role |
|---|---|---|
| `holdwatch-receiver` | 8099 | Webhook intake, signature verification, fail-closed |
| `holdwatch-dashboard` | 8080 | Dashboard |
| `holdwatch-tunnel` | — | Quick tunnels (dev access only, not for the submission) |
| `render-keepalive.timer` | — | Pings Render every 8 min |

**Render** — the public URLs above. Kept running deliberately as the judge-facing
entry point.

---

## The security fix this deployment produced

The Render receiver was **accepting forged payloads** — `{"received": true}` —
because no `webhook_id` was configured there, so signature verification was skipped
entirely. The VPS env file supplies it, so verification now runs:

```
POST forged event -> HTTP 400 {"error": "signature verification failed"}
events stored     -> 0
```

Fail-closed: with no `webhook_id`, the receiver returns `503` and stores nothing,
rather than accepting an event it cannot authenticate.

**To fix Render's receiver too:** add `PAYPAL_WEBHOOK_ID` in its Environment tab.

---

## Outstanding

### AI layer is off

`GEMINI_API_KEY` is empty in `/root/.config/holdwatch/holdwatch.env`, so the
dashboard renders entirely from the deterministic rule engine — the documented
fallback, and it works.

```bash
echo 'GEMINI_API_KEY=*** >> /root/.config/holdwatch/holdwatch.env
sudo systemctl restart holdwatch-dashboard
```

### PayPal's webhook is registered (fixed 2026-10-03)

```
https://holdwatch-receiver.onrender.com   (webhook 10530851TK1789235, 18 events)
```

**Known PayPal sandbox behaviour:** completed orders do not reliably produce a
webhook delivery. Verified repeatedly — `/v1/notifications/webhook-events`
returns `404` with zero delivery attempts logged, for both receivers, across
multiple approved payments and `simulate-event` calls. The registration itself is
correct and confirmed from PayPal's API.

### Live delivery was observed once

A buyer-approved checkout produced `CHECKOUT.ORDER.APPROVED` (order
`52A89694AB3486153`, USD 4,200.00) delivered to the local receiver and verified
`SUCCESS` against PayPal's API. That event, and the six others in
`events/`, are the committed payloads the deployed dashboard renders.

---

## Operating it

```bash
systemctl status holdwatch-dashboard holdwatch-receiver holdwatch-tunnel
systemctl restart holdwatch-dashboard
journalctl -u holdwatch-receiver -f          # live receiver log
tail -f /root/.config/holdwatch/tunnel-dashboard.log   # dev tunnel URL
```

## Secrets

`/root/.config/holdwatch/holdwatch.env`, mode 600, gitignored. Verified: no secret
value appears in any git blob across all history.
