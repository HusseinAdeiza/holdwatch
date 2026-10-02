# HoldWatch — demo video

**Final cut:** `out/HoldWatch_DEMO.mp4` — **76.66s**, 1920×1080, h264/yuv420p + AAC
stereo, 7.36 MB. Under the brief's 3-minute limit and inside our own 90s target.

Rebuild with `bash assemble.sh`. It derives every cut from the *measured* length
of each voiceover clip, not from estimates in the script.

---

## Timeline

| Beat | Length | Picture | Source |
|---|---|---|---|
| 1 — persona | 14.3s | Four drawn cards: name → the $4,200 job → the freeze | `make_cards.py` |
| 2 — reveal | 7.0s | Title card | `make_cards.py` |
| 3 — **demo** | 21.7s | Live dashboard, $4,200 order card | Playwright capture |
| 4 — under the hood | 17.4s | Dashboard, slowed to 0.8× | Playwright capture |
| 5 — montage | 7.4s | Three 2.5s cuts | Playwright capture |
| 6 — payoff | 9.0s | HOLD. TOLD. DONE. end card | `make_cards.py` |

## What is real in it

Everything on screen came from the running product:

- **`USD 4,200.00` · John Doe · `INV2-MEKE-NY55-4ZUC-26W7`** — a real PayPal
  sandbox checkout that completed, with the webhook signature verified against
  PayPal's own `verify-webhook-signature` API.
- **CAUSE UNKNOWN** — the product's honest state. PayPal does not disclose a
  reason in these payloads, so the UI says so rather than inventing one.
- **`USD 1.00` held payout** — the hold-mechanics card, from `simulate-event`.

**The $4,200 order is APPROVED/COMPLETED, not held.** The video does not imply
otherwise: the persona beat establishes the freeze, the dashboard beat shows a
real payment being explained, and the `1.00` held payout demonstrates hold
handling. Two true things, not one false composite.

## Recording

`record_motion.mjs` drives the live app in a real browser and records via
Playwright. Two problems solved along the way, both recorded in the script:

- The dashboard replaces `#feed` every 5s, detaching element handles mid-shot.
  The capture pins the DOM for the duration.
- `ffmpeg -i file` with no output **always exits 32**, which killed `assemble.sh`
  on its first line under `set -e`. Probes now use `|| true`.

## Audio

TTS via Hermes (`text_to_speech`, Edge provider). Mixed at mean −25.2 dB, max
−5.1 dB. Per-beat speed 1.05–1.40 to land the total at 76.7s; a first pass at
slower pacing came out at **99.3s**, over budget, so the VO was tightened rather
than the visuals being rushed or the video padded.

**There is no music bed.** The brief does not require one and silence-plus-voice
is clean; a licensed track would also need clearing for public use.

## To regenerate

```bash
python3 make_cards.py                      # persona / title / end cards
node /root/holdwatch-site/scripts/record_motion.mjs   # needs the app running
bash assemble.sh                            # cut + lay VO
```

The app must be live first:

```bash
python3 receiver.py --port 8099 &
GEMINI_API_KEY=… python3 app.py --port 8080 &
```
