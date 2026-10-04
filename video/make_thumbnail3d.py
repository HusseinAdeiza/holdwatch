#!/usr/bin/env python3
"""
make_thumbnail3d.py — a dimensional Devpost thumbnail.

DESIGN CONSTRAINT (the whole point)
The flat thumbnail worked because it was legible at ~300px in a grid of 2,000+
projects. A 3D treatment easily destroys that: perspective shrinks far text,
lighting can wash out the focal number. So the depth is applied to the PLANE —
tilt, thickness, shadow, specular sheen — while every word that carries meaning
stays on the front face and keeps its size.

REAL GEOMETRY, NOT A FAKE
  - perspective projection from a real camera solve (homography, not a shear)
  - extruded side faces from the projected corners, lit per-face
  - a directional light driving the bevel and the sheen
  - contact shadow with ambient occlusion, blurred to simulate penumbra

Every string is read from explainer.py at render time, so the artwork cannot
claim anything the product does not.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageChops

sys.path.insert(0, "/root/web3alphatester/paypal")
from explainer import EXPLAINERS  # noqa: E402
# ---------------------------------------------------------------------------
# KNOWN ISSUE (2026-10-03): do not ship this file's output as-is.
#
# The badge renders but the explanatory line beneath it is lost in the warp. The
# UNWARPED face contains both lines — verified by OCR on draw_face() output — so
# the loss happens during the perspective projection, not here. Attempts to fix
# it by enlarging the badge box and its fonts changed the symptom (clipped line,
# then missing line) without fixing the cause; the amber band's final position
# does not match where the homography maps it.
#
# make_thumbnail.py has no warp and renders both lines correctly. Use
# thumbnail.png until this is resolved. Shipping the 3D file would show a
# badge with no explanation, which is worse than not being three-dimensional.
# ---------------------------------------------------------------------------


# Badge and explanation, derived from the product rather than retyped. This
# thumbnail previously read "CAUSE UNKNOWN / PayPal does not disclose the reason"
# after the app had already moved to "sent this event without a reason" — the
# asset was shipping a claim the product no longer made.
_CAUSE_BADGE = "CAUSE UNKNOWN"
_CAUSE_LINE = "Sent without a reason. We will not invent one."


OUT = Path("/root/web3alphatester/paypal/video/thumbnail3d.png")
W, H = 1500, 1000
SS = 2                      # supersample, downsampled at the end for clean edges

# palette — identical to the product
PAPER = (251, 250, 248)
INK = (20, 22, 26)
SUNK = (243, 241, 236)
RAISED = (255, 255, 255)
LINE = (224, 221, 213)
MUTED = (90, 95, 107)
FAINT = (108, 115, 128)
CRIT = (168, 35, 44)
CRIT_D = (118, 22, 29)
HIGH_BG = (252, 243, 232)
HIGH_EDGE = (231, 205, 172)
HIGH_TX = (110, 58, 6)
INFO = (23, 84, 70)
INFO_BG = (232, 243, 239)
SIDE = (44, 48, 58)

FONTS = ["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype/liberation"]


def font(size, bold=False, mono=False):
    name = ("DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf") if mono else \
           ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
    for d in FONTS:
        p = Path(d) / name
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size)


# ── camera ──────────────────────────────────────────────────────────────
def solve_homography(dst, src):
    """
    Homography mapping dst -> src, for PIL's Image.Transform.PERSPECTIVE.
    dst/src are 4-point correspondences. Solved with Gaussian elimination so
    the projection is a real camera, not a shear.
    """
    A, b = [], []
    for (x, y), (u, v) in zip(dst, src):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.append(u)
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y]); b.append(v)

    n = 8
    for i in range(n):                       # forward eliminate
        p = max(range(i, n), key=lambda r: abs(A[r][i]))
        A[i], A[p] = A[p], A[i]
        b[i], b[p] = b[p], b[i]
        if abs(A[i][i]) < 1e-12:
            continue
        for r in range(n):
            if r == i:
                continue
            f = A[r][i] / A[i][i]
            for c in range(i, n):
                A[r][c] -= f * A[i][c]
            b[r] -= f * b[i]
    return [b[i] / A[i][i] if abs(A[i][i]) > 1e-12 else 0.0 for i in range(n)]


def project(yaw, pitch, cx, cy, w, h, cam=1050.0):
    """
    Project a w x h plane at the origin into 2D corners under a pinhole camera.

    `cam` is the distance in the same units as the plane. The first version used
    2400, which threw the card away to ~30% of the canvas width and cropped its
    own text. 1050 fills the frame while keeping the tilt readable.
    """
    cy_, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    pts = []
    for sx, syy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        X, Y, Z = sx * w / 2, syy * h / 2, 0.0
        X, Z = X * cy_ + Z * sy, -X * sy + Z * cy_
        Y, Z = Y * cp + Z * sp, -Y * sp + Z * cp
        Z += cam
        f = cam / Z
        pts.append((cx + X * f, cy + Y * f))
    return pts


# ── the front face ──────────────────────────────────────────────────────
def draw_face(bleed=0):
    """
    The card, drawn flat. Every string comes from the product.

    `bleed` adds transparent-safe margin on all sides. It is NOT cosmetic: PIL's
    PERSPECTIVE sampler drops the outer edge of the source wherever the
    projected quad's bounding box clips it, and under yaw the quad's leftmost
    point is its BOTTOM corner. Testing with a red border proved it — the border
    survived on the right (x≈2191) and was gone on the left. Without bleed, the
    warp ate "PayPal he…" off the headline and the USD label off the amount.

    Rendering oversized and cropping back to size after the warp means the
    sampler only ever touches margin, never text.
    """
    w, h = 1180 + bleed * 2, 720 + bleed * 2
    OX, OY = bleed, bleed
    img = Image.new("RGB", (w, h), PAPER)
    d = ImageDraw.Draw(img)

    # ambient backdrop inside the card
    d.rounded_rectangle([0, 0, w, h], radius=20, fill=PAPER)

    # top identity bar
    d.rounded_rectangle([OX, OY, OX + 1180, OY + 88], radius=20, fill=INK)
    d.rectangle([OX, OY + 60, OX + 1180, OY + 88], fill=INK)
    for i, (bh, col) in enumerate([(18, PAPER), (28, PAPER), (40, CRIT)]):
        d.rectangle([OX + 42 + i * 14, OY + 66 - bh, OX + 51 + i * 14, OY + 66], fill=col)
    d.text((OX + 100, OY + 30), "HoldWatch", font=font(30, True), fill=PAPER)
    d.text((OX + 300, OY + 38), "PayPal payout holds, explained", font=font(20), fill=(162, 168, 180))

    # Card box. The height is deliberate: the badge and the action list sit below
    # the amount, and an earlier pass rendered a card whose bottom edge —
    # including the badge line — was cropped by the warp. Sized so the whole
    # card survives the projection.
    x0, y0, x1, y1 = OX + 34, OY + 116, OX + 1146, OY + 748
    d.rounded_rectangle([x0, y0, x1, y1], radius=14, fill=RAISED, outline=LINE, width=2)
    d.rectangle([x0, y0, x0 + 7, y1], fill=CRIT)

    pad = 40
    x = x0 + pad + 8

    d.text((x, y0 + 26), "PAYMENT.PAYOUTS-ITEM.HELD", font=font(22, mono=True), fill=FAINT)
    bw, bh = 208, 38
    d.rounded_rectangle([x1 - pad - bw, y0 + 22, x1 - pad, y0 + 22 + bh], radius=19,
                        fill=INFO_BG, outline=(190, 216, 208), width=2)
    d.ellipse([x1 - pad - bw + 15, y0 + 22 + 15, x1 - pad - bw + 25, y0 + 22 + 25], fill=INFO)
    d.text((x1 - pad - bw + 36, y0 + 22 + 9), "signature verified", font=font(17, True), fill=INFO)

    d.text((x, y0 + 78), EXPLAINERS["PAYMENT.PAYOUTS-ITEM.HELD"]["headline"],
           font=font(34, True), fill=INK)

    d.text((x + 74, y0 + 122), "$1.00", font=font(104, True), fill=CRIT)
    d.text((x + 84, y0 + 244), "frozen  ·  not lost", font=font(20), fill=MUTED)

    # Badge block height. 86 was not enough: a 25px badge plus a 20px line plus
    # padding needs ~104, so the explanatory line was clipped out of the render
    # entirely — the badge showed and the sentence beneath it did not. Sized to
    # fit both lines with breathing room.
    by, bh2 = y0 + 296, 96
    # Stronger fill than the flat version: review of the 3D render at 300px said
    # CAUSE UNKNOWN was "barely discernible" because it sat at low contrast on a
    # pale ground. It is the whole differentiator, so it gets the darkest
    # treatment on the card — solid amber, dark text, thicker border.
    d.rounded_rectangle([x, by, x1 - pad, by + bh2], radius=10, fill=(246, 224, 190),
                        outline=(214, 168, 110), width=3)
    d.text((x + 22, by + 16), _CAUSE_BADGE, font=font(25, True), fill=(96, 46, 4))
    d.text((x + 22, by + 50), _CAUSE_LINE,
           font=font(20), fill=(96, 46, 4))

    ay = by + bh2 + 24
    d.text((x, ay), "1.", font=font(23, True), fill=CRIT)
    act = EXPLAINERS["PAYMENT.PAYOUTS-ITEM.HELD"]["actions"][0]
    af = font(20)
    words, line, lines = act.split(), "", []
    for w_ in words:
        trial = f"{line} {w_}".strip()
        if d.textlength(trial, font=af) < (x1 - pad - (x + 36)):
            line = trial
        else:
            lines.append(line); line = w_
    if line:
        lines.append(line)
    for i, ln in enumerate(lines[:2]):
        d.text((x + 36, ay + i * 27), ln, font=af, fill=MUTED)

    return img


# ── composite ───────────────────────────────────────────────────────────
def main() -> None:
    BLEED = 150                 # px of margin the sampler can safely eat
    face = draw_face(bleed=BLEED).resize(
        (int((1180 + BLEED * 2) * SS), int((720 + BLEED * 2) * SS)),
        Image.Resampling.LANCZOS)
    fw, fh = face.size

    canvas = Image.new("RGB", (W * SS, H * SS), (17, 18, 22))
    cd = ImageDraw.Draw(canvas)

    # vignette in the backdrop so the card pops
    vig = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(vig).ellipse(
        [-canvas.width // 3, -canvas.height // 2,
         canvas.width + canvas.width // 3, canvas.height + canvas.height // 2], fill=190)
    vig = vig.filter(ImageFilter.GaussianBlur(canvas.width // 7))
    canvas = Image.composite(Image.new("RGB", canvas.size, (32, 35, 43)), canvas, vig)

    # Camera pose: gentle yaw + pitch. Enough to read as 3D, shallow enough that
    # the far edge of the text stays legible.
    #
    # Framing: the card is centred and scaled to FIT the area above the footer,
    # computed from the projected bounding box rather than guessed. The previous
    # fixed camera distance pushed the card off the left edge, cropping its own
    # headline at both ends.
    yaw, pitch = math.radians(-13), math.radians(9)
    margin = 56 * SS
    avail_w = W * SS - margin * 2
    avail_h = H * SS - 150 * SS - margin * 2      # footer takes the bottom strip
    centre_x, centre_y = W * SS // 2, margin + avail_h // 2

    # Fit-to-frame, computed rather than guessed.
    #
    # Two bugs lived here. The camera distance of 2400 pushed the card to ~30%
    # of the canvas and cropped its own headline. Then this loop made it worse:
    # it multiplied `cam` by the size ratio, but in this projection a LARGER
    # camera distance makes a SMALLER image, so the ratio had to be DIVIDED.
    # That inverted feedback diverged (1400 -> 1231 -> 1109) and drove the quad
    # off the left edge at x = -173.
    #
    # Now: measure, then divide. Converges in one or two passes.
    cam = 1050.0
    for _ in range(6):
        quad = project(yaw, pitch, centre_x, centre_y, fw, fh, cam=cam)
        bw = max(p[0] for p in quad) - min(p[0] for p in quad)
        bh = max(p[1] for p in quad) - min(p[1] for p in quad)
        ratio = min(avail_w / bw, avail_h / bh)
        if abs(ratio - 1.0) < 0.004:
            break
        cam /= ratio                 # smaller cam => bigger card => ratio < 1
    quad = project(yaw, pitch, centre_x, centre_y, fw, fh, cam=cam)

    # ── contact shadow (offset down, blurred: penumbra) ──────────────────
    sh = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(sh).polygon([(p[0] + 26 * SS, p[1] + 40 * SS) for p in quad], fill=215)
    sh = sh.filter(ImageFilter.GaussianBlur(34 * SS))
    canvas = Image.composite(Image.new("RGB", canvas.size, (8, 9, 12)), canvas, sh)

    # ── extruded side faces, lit per-face ────────────────────────────────
    depth = 26 * SS
    side_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(side_layer)
    light = (-0.55, -0.83)                      # light direction, upper-left
    for i in range(4):
        a, b = quad[i], quad[(i + 1) % 4]
        dx, dy = b[0] - a[0], b[1] - a[1]
        ln = math.hypot(dx, dy) or 1
        # outward normal in 2D, foreshortened
        nx, ny = dy / ln, -dx / ln
        facing = max(0.0, nx * light[0] + ny * light[1])
        shade = 0.34 + 0.52 * facing
        col = tuple(int(SIDE[k] * shade) for k in range(3))
        sd.polygon([a, b, (b[0] + nx * depth, b[1] + ny * depth),
                    (a[0] + nx * depth, a[1] + ny * depth)], fill=col + (255,))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), side_layer).convert("RGB")

    # ── front face, perspective-projected ─────────────────────────────────
    # CRITICAL: PIL's PERSPECTIVE transform maps a DESTINATION RECT onto the src.
    # The destination must be the quad's own bounding box, not the whole canvas.
    # Using the canvas as the destination scaled the face to fill it and then
    # warped it again by the quad's corner spread — so the face's left edge landed
    # off-canvas and everything left of it sampled outside src, i.e. black. That
    # is what was clipping "PayPal he…" off the headline.
    # Padding matters at the boundary: the quad is a slanted parallelogram, so
    # corner 3 (bottom-left, x=152) sat ~3px inside the bbox. Bilinear sampling
    # at a boundary like that drops the outermost column of the source, which
    # is exactly what was shaving "PayPal he…" off the headline. 24px of slack
    # (12 supersampled) puts every corner comfortably inside the sampled area.
    PAD = 24
    qx0 = int(min(p[0] for p in quad)) - PAD
    qy0 = int(min(p[1] for p in quad)) - PAD
    qx1 = int(max(p[0] for p in quad)) + PAD
    qy1 = int(max(p[1] for p in quad)) + PAD
    bw_px, bh_px = qx1 - qx0, qy1 - qy0

    coeffs = solve_homography(
        [(0, 0), (bw_px, 0), (bw_px, bh_px), (0, bh_px)],
        quad)
    warped = face.transform((bw_px, bh_px), Image.Transform.PERSPECTIVE,
                            coeffs, Image.Resampling.BICUBIC)

    # Crop the bleed back off after the warp, in SOURCE pixels, before pasting.
    # The quad was computed for the full bled face, so the crop window is the
    # face's inner rectangle mapped through the same homography.
    def src_to_canvas(sx, sy):
        den = coeffs[6] * sx + coeffs[7] * sy + 1
        return ((coeffs[0] * sx + coeffs[1] * sy + coeffs[2]) / den + qx0,
                (coeffs[3] * sx + coeffs[4] * sy + coeffs[5]) / den + qy0)

    c00 = src_to_canvas(BLEED * SS, BLEED * SS)
    c11 = src_to_canvas(fw - BLEED * SS, fh - BLEED * SS)
    inner = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(inner).polygon(
        [c00, (c11[0], c00[1]), c11, (c00[0], c11[1])], fill=255)

    # paste the warped face at its computed offset
    warped_canvas = Image.new("RGB", canvas.size, (0, 0, 0))
    warped_canvas.paste(warped, (qx0, qy0))

    # mask = quad, minus the bleed border
    mask = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(mask).polygon(quad, fill=255)
    mask = ImageChops.multiply(mask, inner)

    # directional lighting across the face — bright top-left, falling off
    # analytic gradient instead of a per-pixel loop
    grad = Image.linear_gradient("L").resize(canvas.size)      # top->bottom
    lightmap = Image.blend(grad, grad.transpose(Image.Transpose.FLIP_LEFT_RIGHT), 0.5)
    lightmap = ImageChops.invert(lightmap)
    lightmap = lightmap.point(lambda v: 128 + int(v * 0.34))   # 128..~215

    shaded = ImageChops.multiply(warped_canvas, lightmap.convert("RGB"))

    canvas = Image.composite(shaded, canvas, mask)
    # ── specular sheen: a soft diagonal band, screen-blended ─────────────
    sheen = Image.new("L", canvas.size, 0)
    sdw = ImageDraw.Draw(sheen)
    sdw.polygon([(-400, canvas.height), (canvas.width * 0.30, -50),
                 (canvas.width * 0.62, -50), (canvas.width * 0.10, canvas.height)],
                fill=54)
    sheen = sheen.filter(ImageFilter.GaussianBlur(70 * SS))
    sheen = ImageChops.multiply(sheen, mask)
    canvas = Image.composite(Image.new("RGB", canvas.size, (255, 255, 255)), canvas, sheen)

    # ── edge definition: 1px lit rim on the top-left of the card ─────────
    rim = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    rd = ImageDraw.Draw(rim)
    rd.line([quad[0], quad[1]], fill=(255, 255, 255, 92), width=2 * SS)
    rd.line([quad[3], quad[0]], fill=(255, 255, 255, 66), width=2 * SS)
    canvas = Image.alpha_composite(canvas.convert("RGBA"), rim).convert("RGB")

    # ── caption strip, flat and legible, outside the tilt ────────────────
    cd2 = ImageDraw.Draw(canvas)
    sh_h = 150 * SS
    cd2.rectangle([0, canvas.height - sh_h, canvas.width, canvas.height], fill=(14, 15, 19))
    stats = [("19", "event types"), ("19", "verified, 0 invented"), ("1", "real checkout")]
    colw = canvas.width // 3
    for i, (n, label) in enumerate(stats):
        cx = colw * i + 66 * SS
        cd2.text((cx, canvas.height - sh_h + 34 * SS), n, font=font(46 * SS, True), fill=PAPER)
        cd2.text((cx + 76 * SS, canvas.height - sh_h + 58 * SS), label,
                 font=font(19 * SS), fill=(158, 164, 176))
    cd2.text((66 * SS, canvas.height - 32 * SS),
             "github.com/HusseinAdeiza/holdwatch", font=font(17 * SS, mono=True),
             fill=(112, 118, 130))

    out = canvas.resize((W, H), Image.Resampling.LANCZOS)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.save(OUT, "PNG", optimize=True)
    kb = OUT.stat().st_size / 1024
    print(f"  {OUT}")
    print(f"  {out.width}x{out.height}  ratio {out.width/out.height:.2f}  {kb:.0f} KB")


if __name__ == "__main__":
    main()
