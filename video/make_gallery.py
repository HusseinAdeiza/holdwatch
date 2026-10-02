#!/usr/bin/env python3
"""
make_gallery.py — build the Devpost image gallery at 3:2.

Devpost asks for 3:2 (1800x1200) and caps each file at 5 MB. Our raw captures
are 1920x1080 (16:9) or tight element crops at odd ratios, so they were not
uploadable as-is. This renders purpose-built gallery frames from the LIVE app at
the right size, with a caption strip, so every image on the public page is a real
product surface rather than a screenshot someone cropped in a hurry.

No invented content: every figure comes from the running product.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path("/root/web3alphatester/paypal/video/gallery")
OUT.mkdir(parents=True, exist_ok=True)
W, H = 1800, 1200          # 3:2, as Devpost requests
CAPTION = 92                # caption strip height

PAPER = (18, 20, 26)
STRIP = (12, 14, 18)
INK = (242, 241, 237)
MUTED = (150, 158, 172)
CRIT = (232, 93, 104)
INFO = (79, 209, 197)

FONT_DIRS = ["/usr/share/fonts/truetype/dejavu",
             "/usr/share/fonts/truetype/liberation"]


def font(size: int, bold: bool = False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for d in FONT_DIRS:
        p = Path(d) / name
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size)


def frame(src_png: Path, out_name: str, title: str, sub: str, accent=INFO):
    """Letterbox a real screenshot into 3:2 with a caption strip."""
    src = Image.open(src_png).convert("RGB")
    body_h = H - CAPTION
    # fit width, keep aspect, centre vertically in the body
    scale = W / src.width
    nh = int(src.height * scale)
    if nh > body_h:
        nh = body_h
        nw = int(src.width * (body_h / src.height))
        src = src.resize((nw, body_h), Image.Resampling.LANCZOS)
        x = (W - nw) // 2
    else:
        src = src.resize((W, nh), Image.Resampling.LANCZOS)
        x = 0
    img = Image.new("RGB", (W, H), PAPER)
    img.paste(src, (x, (body_h - nh) // 2))
    d = ImageDraw.Draw(img)

    # caption strip
    d.rectangle([0, body_h, W, H], fill=STRIP)
    d.line([(0, body_h), (W, body_h)], fill=(44, 48, 56), width=2)
    d.rectangle([56, body_h + CAPTION // 2 - 5, 66, body_h + CAPTION // 2 + 5],
                fill=accent)
    d.text((84, body_h + 26), title, font=font(30, True), fill=INK)
    d.text((84, body_h + 60), sub, font=font(20), fill=MUTED)
    p = OUT / out_name
    img.save(p, "PNG", optimize=True)
    kb = p.stat().st_size / 1024
    print(f"  {out_name:30s} {img.width}x{img.height}  {kb:7.1f} KB  "
          f"{'OK' if kb < 5 * 1024 else 'TOO BIG'}")


if __name__ == "__main__":
    S = Path("/root/web3alphatester/paypal/video/shots")

    frame(S / "10_hero.png", "01_dashboard.png",
          "HoldWatch — PayPal events, explained",
          "Live webhook stream, severity-ordered. Every card is signature-verified by PayPal's API.",
          INFO)

    frame(S / "11_order_4200.png", "02_order_4200.png",
          "A real $4,200 payment, verified",
          "CHECKOUT.ORDER.APPROVED — a completed sandbox checkout. Amount, payer and invoice read straight from the payload.",
          INFO)

    frame(S / "12_held_payout.png", "03_held_payout.png",
          "A held payout, in plain language",
          "PAYMENT.PAYOUTS-ITEM.HELD — the money is frozen, not lost. Ranked actions follow.",
          CRIT)

    frame(S / "14_event_data.png", "04_payload.png",
          "Every field one click deep",
          "The raw payload behind the explanation, so any claim can be checked against its source.",
          INFO)

    print(f"\n  -> {OUT}")
