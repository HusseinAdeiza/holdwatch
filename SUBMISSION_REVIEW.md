# Review — the live Devpost submission

Checked against what the product actually does today. Verdict: strong entry, four
fixes, two of them genuine contradictions.

---

## 🔴 1. The video link is the OLD recording

| | |
|---|---|
| Devpost links | `youtu.be/bFOglGDKJpM` — 76.66s, recorded **before** the fixes |
| Current build | 80.56s, re-recorded, correct copy on every frame |

The old video shows *"PayPal does not disclose the reason in this event"* on
screen. The live product says *"PayPal sent this event without a reason."* The
narration in the old video also contradicts its own screen — the exact conflation
a commenter publicly called out.

**Fix:** upload `video/out/HoldWatch_DEMO.mp4` and swap the URL in both places —
the "Try it out" link and the embedded video field.

---

## 🔴 2. The story still uses the conflated wording

Live page:

> **CAUSE UNKNOWN** — *"PayPal does not disclose the reason in this event. We will
> not invent one."*
>
> Only 1 of our 19 explanations states a known cause. For the other 18, PayPal
> doesn't disclose a reason in the payload.

This is precisely what we changed after the comment, and it is **still the most
quotable line on the page**. Replace with the four-state version:

> Only 1 of our 19 explanations states a known cause. A commenter asked how we
> tell "PayPal withheld a reason" from "we never received the event" — and at the
> time we couldn't, because our own completed capture produced no webhook at all
> while the dashboard implied a reason had been withheld. Four states now:
> **confirmed** · **cause unknown** (the event arrived without one) ·
> **awaiting webhook** (we hold a record, no event yet) · **unresolvable** (an id
> we cannot look up).

---

## 🟡 3. The strongest security story is missing

The page says *"A verifier that always says yes is decoration"* and explains the
CRC32 failure. Good — but it never mentions that **a deployed instance actually
accepted a forged payload**, twice, because verification was skipped when no
webhook id was configured.

That is a stronger story than the CRC32 anecdote: it proves we tested against
attackers' behaviour rather than our own assumptions, and it makes the fail-closed
design obvious rather than asserted. Worth one paragraph.

Also worth stating plainly: **the receiver now fails closed.** With no webhook id
it returns `503` and stores nothing. Post the forgery to
`holdwatch-receiver.onrender.com` and get `400` — the landing page lets a judge
verify this in one click.

---

## 🟡 4. Two small inconsistencies

- The story says *"a hard 8-second deadline."* The follow-up deadline is now
  **20s** (8s was rejecting valid answers). The site and README say 20s.
- **Try it yourself** lists only the three commands. Add the deployed URLs above
  them — a judge who wants to run something should not have to start from zero.

---

## ✅ What is genuinely strong — leave it alone

- **The honesty section.** "The ground truth is mine, not PayPal's," "I stopped at
  0.80 rather than tune to 1.00," "weaker claim than prediction, and it's true."
  Judges reward this. Do not soften it.
- **The prediction pivot** with the actual `403 NOT_AUTHORIZED` responses.
- **The API-quirk detail** (`billing_info`, `WEBHOOK_URL_ALREADY_EXISTS`,
  delete-then-create). Reads like someone who actually built it.
- **Tags** — 13, all verifiable in the repo.
- **All five Try-it-out links** work and are permanent Render URLs.
- **Gallery** — 4 images, correctly paired, captions honest.
- **No pricing claims, no customer claims, no traction invented.** Clean.

---

## Priority

1. Swap the video (a judge will watch it first)
2. Fix the story's cause paragraph (it is the contradiction, verbatim)
3. Add the fail-closed security paragraph
4. Correct 8s → 20s, add deployed URLs

Fix 1 and 2 and the entry is internally consistent. Do those two first.
