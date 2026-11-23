"""Code-drawn sample designs for tests and offline demos (no AI needed)."""
from __future__ import annotations

import io
import math

from PIL import Image, ImageDraw


def mountain_scene(floating_moon: bool = True, thin_bridge: bool = False, size: int = 1536) -> bytes:
    w, h = size, int(size * 2 / 3)
    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)
    # base bar + mountains
    d.rectangle((int(w * 0.06), int(h * 0.84), int(w * 0.94), int(h * 0.90)), fill=0)
    peaks = [(0.06, 0.84), (0.22, 0.38), (0.33, 0.58), (0.50, 0.18), (0.64, 0.52), (0.78, 0.32), (0.94, 0.84)]
    d.polygon([(x * w, y * h) for x, y in peaks], fill=0)
    # snow caps cut out (holes)
    d.polygon([(0.50 * w, 0.20 * h), (0.46 * w, 0.30 * h), (0.50 * w, 0.27 * h), (0.54 * w, 0.30 * h)], fill=255)
    # pine trees standing on the base
    for i, x in enumerate([0.12, 0.17, 0.83, 0.88]):
        top = 0.52 + (i % 2) * 0.06
        d.polygon([(x * w, top * h), ((x - 0.035) * w, 0.85 * h), ((x + 0.035) * w, 0.85 * h)], fill=0)
    if floating_moon:
        d.ellipse((0.74 * w, 0.08 * h, 0.84 * w, 0.23 * h), fill=0)
    if thin_bridge:  # bird attached by a hairline
        d.ellipse((0.30 * w, 0.10 * h, 0.36 * w, 0.16 * h), fill=0)
        d.line((0.33 * w, 0.16 * h, 0.33 * w, 0.62 * h), fill=0, width=3)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def clock_face(size: int = 1400) -> bytes:
    img = Image.new("L", (size, size), 255)
    d = ImageDraw.Draw(img)
    c, r = size / 2, size * 0.44
    d.ellipse((c - r, c - r, c + r, c + r), fill=0)
    d.ellipse((c - r * 0.90, c - r * 0.90, c + r * 0.90, c + r * 0.90), fill=255)
    for k in range(12):
        a = math.radians(k * 30)
        long = k % 3 == 0
        r0 = r * (0.66 if long else 0.74)
        x0, y0 = c + math.sin(a) * r0, c - math.cos(a) * r0
        x1, y1 = c + math.sin(a) * r * 0.92, c - math.cos(a) * r * 0.92
        d.line((x0, y0, x1, y1), fill=0, width=int(size * (0.035 if long else 0.02)))
    # abstract spokes joining the ring to the hub
    for k in range(6):
        a = math.radians(k * 60 + 15)
        pts = []
        for t in range(0, 41):
            rr = r * (0.10 + 0.80 * t / 40)
            aa = a + 0.9 * math.sin(t / 40 * math.pi) * 0.5
            pts.append((c + math.sin(aa) * rr, c - math.cos(aa) * rr))
        d.line(pts, fill=0, width=int(size * 0.018), joint="curve")
    d.ellipse((c - r * 0.14, c - r * 0.14, c + r * 0.14, c + r * 0.14), fill=0)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()
