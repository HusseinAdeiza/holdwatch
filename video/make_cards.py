#!/usr/bin/env python3
"""
make_cards.py — render the motion-graphic cards the demo needs.

Beat 1 (persona) and Beat 6 (end card) have no screen capture to work from, so
they are drawn. Drawn in the same restrained palette as the product site — warm
paper, near-black ink, signal colours only — so the video reads as one piece
rather than a screencast with title cards bolted on.

Outputs 1920x1080 PNGs. No external font dependency; uses the same stack as the
site so the two match.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path("/root/web3alphatester/paypal/video/cards")
OUT.mkdir(parents=True, exist_ok=True)

W, H = 1920, 1080
PAPER = (251, 250, 248)
INK = (20, 22, 26)
MUTED = (90, 95, 107)
FAINT = (102, 109, 121)
CRIT = (168, 35, 44)
HIGH = (138, 75, 8)
OK = (27, 94, 79)
LINE = (228, 225, 218)

FONT_DIRS = [
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/liberation",
    "/usr/local/share/fonts",
]


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = (["DejaVuSans-Bold.ttf"] if bold else ["DejaVuSans.ttf"])
    for d in FONT_DIRS:
        for n in names:
            p = Path(d) / n
            if p.exists():
                return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size)


def centre(d: ImageDraw.ImageDraw, text: str, f, y: int, fill) -> None:
    w = d.textbbox((0, 0), text, font=f)[2]
    d.text(((W - w) / 2, y), text, font=f, fill=fill)


def card_beat1_lines(stage: int) -> Image.Image:
    """
    Beat 1, four stages. stage 0 = black, 1 = name, 2 = the job, 3 = the freeze.
    Kept as separate frames so ffmpeg can hold each one cleanly.
    """
    img = Image.new("RGB", (W, H), INK)
    d = ImageDraw.Draw(img)

    if stage == 0:
        return img  # half a second of silence before anything appears

    if stage == 1:
        centre(d, "This is Maya.", font(104, True), 430, PAPER)
        centre(d, "26. Lagos. Freelance designer.", font(40), 580, (168, 174, 186))

    elif stage == 2:
        centre(d, "She shipped work worth", font(52), 360, (168, 174, 186))
        centre(d, "$4,200.00", font(148, True), 440, PAPER)
        centre(d, "Paid. Completed. Confirmed by the client.", font(40), 640,
               (168, 174, 186))

    elif stage == 3:
        centre(d, "Three days later PayPal froze every cent.", font(52), 300,
               PAPER)
        # the balance
        d.rounded_rectangle([W // 2 - 400, 420, W // 2 + 400, 700], radius=18,
                            fill=(28, 30, 36), outline=(58, 62, 72), width=2)
        d.text((W // 2 - 340, 462), "Available balance", font=font(28),
               fill=(140, 148, 162))
        d.text((W // 2 - 340, 510), "$0.00", font=font(96, True), fill=CRIT)
        d.text((W // 2 - 340, 630), "$4,200.00 pending — no reason given",
               font=font(26), fill=FAINT)
        # the notification
        d.rounded_rectangle([W // 2 - 400, 740, W // 2 + 400, 830], radius=12,
                            fill=(58, 22, 26), outline=(120, 40, 46), width=2)
        d.ellipse([W // 2 - 366, 772, W // 2 - 348, 790], fill=CRIT)
        d.text((W // 2 - 326, 766), "Your account has been limited.",
               font=font(30, True), fill=(232, 160, 164))
    return img


def card_end() -> Image.Image:
    img = Image.new("RGB", (W, H), INK)
    d = ImageDraw.Draw(img)

    # the three-word brand
    words = [("HOLD.", 300, CRIT), ("TOLD.", 470, PAPER), ("DONE.", 640, OK)]
    for text, y, col in words:
        centre(d, text, font(112, True), y, col)

    d.line([(W // 2 - 150, 800), (W // 2 + 150, 800)], fill=(58, 62, 72), width=2)
    centre(d, "HoldWatch", font(40, True), 830, (168, 174, 186))
    centre(d, "github.com/HusseinAdeiza/holdwatch", font(26), 892, FAINT)
    centre(d, "MIT licensed  ·  PayPal AI Hackathon", font(24), 936, (110, 116, 128))
    return img


def card_title() -> Image.Image:
    img = Image.new("RGB", (W, H), INK)
    d = ImageDraw.Draw(img)
    centre(d, "HoldWatch", font(120, True), 440, PAPER)
    centre(d, "PayPal payout holds, explained.", font(42), 610, (168, 174, 186))
    return img


if __name__ == "__main__":
    made = []
    for stage in range(4):
        p = OUT / f"beat1_{stage}.png"
        card_beat1_lines(stage).save(p)
        made.append(p.name)
    (OUT / "end_card.png").write_bytes(b"")
    card_end().save(OUT / "end_card.png")
    made.append("end_card.png")
    card_title().save(OUT / "title.png")
    made.append("title.png")

    for m in made:
        kb = (OUT / m).stat().st_size / 1024
        print(f"  {m:22s} {kb:7.1f} KB")
    print(f"\n  -> {OUT}")
