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

### PayPal's webhook points at a dead tunnel

Registered URL is `https://submitting-jpg-really-musician.trycloudflare.com`,
which no longer exists. Re-point it at whichever receiver is permanent:

```bash
python3 register_webhook.py https://holdwatch-receiver.onrender.com --all
```

Delete-then-create (PayPal has no update verb), so the webhook id **changes** —
update `PAYPAL_WEBHOOK_ID` in the env file and restart the receiver.

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
