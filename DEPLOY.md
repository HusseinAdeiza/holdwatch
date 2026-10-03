# DEPLOY — the VPS deployment

**Status: live, 2/2 services, 0% of a 3-minute job.**

---

## Running now

| Service | systemd unit | Local | Public (quick tunnel) |
|---|---|---|---|
| Dashboard | `holdwatch-dashboard` | `:8080` | `https://donations-towards-sing-noted.trycloudflare.com` |
| Receiver | `holdwatch-receiver` | `:8099` | `https://talent-prot-astrology-harder.trycloudflare.com` |

Both auto-restart. Verified from outside:

```
public dashboard : 7 events, 7 verified, $4,200 present
public receiver  : forged POST -> HTTP 400 "signature verification failed"
                   0 events stored
```

**The receiver now fails closed.** Earlier it accepted a forged payload
(`{"received": true}`) because no `webhook_id` was configured, so verification was
skipped. The systemd env file supplies `PAYPAL_WEBHOOK_ID`, so verification runs
and rejects.

---

## Why the VPS beats Render

Measured, not assumed. The Render instance reported `uptime_s: 6` when I timed it —
it had just woken, so my earlier "0.28s cold start" reading was a **warm** instance
and was wrong. Render's documented worst case from full spin-down is ~50s.

On the VPS the services never stop, so there is no spin-down at all.

Render is left running as a fallback until judging is done. The Devpost link can
move to the VPS at any time without a gap.

---

## ⚠️ The hostnames above are TEMPORARY

They are **quick tunnels**. The hostname is randomly generated and **changes every
time the tunnel restarts** — which systemd will do on any reboot.

`systemctl restart holdwatch-tunnel` → new URLs → the old Devpost link dies.

### Permanent fix — named tunnel (5 minutes, needs you)

1. Create a Cloudflare account (free) and add a domain you control
2. On Cloudflare's dashboard: **Zero Trust → Networks → Tunnels → Create**
3. Run the command it gives you on this box (it authenticates and writes
   `/root/.cloudflared/<id>.json`)
4. Point two public hostnames at it:
   - `holdwatch.yourdomain.com` → `http://localhost:8080`
   - `hooks.yourdomain.com` → `http://localhost:8099`

Once that exists, swap `ExecStart` in `holdwatch-tunnel.service` for
`cloudflared tunnel run holdwatch`, restart, and the URLs are permanent.

**Without this, do not put the quick-tunnel URL in the submission.** A dead link
is worse than a 50-second load.

---

## Outstanding

### 1. AI layer is off (`GEMINI_API_KEY` empty)

The env file has the key slot but no value — it wasn't in the shell when the file
was generated. The dashboard currently renders entirely from the deterministic rule
engine, which is the documented fallback and works fine.

To enable it:

```bash
echo 'GEMINI_API_KEY=YOUR_KEY_HERE' >> /root/.config/holdwatch/holdwatch.env
sudo systemctl restart holdwatch-dashboard
```

### 2. PayPal's webhook still points at the old dead tunnel

Registered URL is `https://submitting-jpg-really-musician.trycloudflare.com`.
Re-point it **after** a permanent hostname exists:

```bash
python3 register_webhook.py https://hooks.yourdomain.com --all
```

PayPal has no update verb, so this is delete-then-create and the webhook id
**changes** — update `PAYPAL_WEBHOOK_ID` in the env file and restart the receiver.

---

## Operating it

```bash
systemctl status holdwatch-dashboard holdwatch-receiver holdwatch-tunnel
systemctl restart holdwatch-dashboard
journalctl -u holdwatch-receiver -f          # live receiver log
tail -f /root/.config/holdwatch/tunnel-dashboard.log   # tunnel URL
```

## Secrets

`/root/.config/holdwatch/holdwatch.env`, mode 600, gitignored, never committed.
Verified: no secret value appears in any git blob across all history.
