"""The name plate under a custom portrait, drawn by code (never by the AI): the text is exact, any name
and any Turkish letter works, and it changes per order without a new drawing.

The plate hangs under the design's lowest row (the base bar the portrait prompt asks for) and the text is
cut through it. Letter counters (the inside of O, B, A, ö...) would fall out as loose parts, so each one
gets a short bridge, like a stencil font.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

from . import config, cutcheck

FONT = "Inter.ttf"
WEIGHT = 800             # Inter is a variable font: heavy strokes cut cleanly
LETTER_FRAC = 0.11       # letter height as a share of the design's height
TEXT_FILL = 0.84         # the text may use this share of the plate's width
PAD_TOP, PAD_BOTTOM = 0.30, 0.42  # plate margins as a share of the letter height (the base bar adds to the top)
TRACKING = 0.07          # extra space between letters, as a share of the font size: metal between cut
                         # letters stays above the minimum width even at small sizes
DEFAULT_TEXT = "Custom Text"


def _letters(text: str, size: int) -> np.ndarray:
    font = ImageFont.truetype(str(config.FONTS / FONT), size)
    try:  # variable font: heavy weight, display optical size; axes are set in the font's own order
        font.set_variation_by_axes([
            WEIGHT if axis["name"] in (b"Weight", "Weight")
            else axis["maximum"] if axis["name"] in (b"Optical size", "Optical size") else axis["default"]
            for axis in font.get_variation_axes()
        ])
    except (OSError, ValueError):  # a static font: keep its own weight
        pass
    gap = size * TRACKING
    widths = [font.getlength(ch) for ch in text]
    _, top, _, bottom = font.getbbox(text)
    width = int(sum(widths) + gap * (len(text) - 1)) + size  # spare room for overhangs, cropped below
    img = Image.new("L", (width, bottom - top + 4), 0)
    draw = ImageDraw.Draw(img)
    x = size / 2
    for ch, adv in zip(text, widths):  # letter by letter, with tracking
        draw.text((x, 2 - top), ch, font=font, fill=255)
        x += adv + gap
    m = np.asarray(img) > 127
    cols = np.flatnonzero(m.any(axis=0))
    return m[:, cols[0]:cols[-1] + 1] if cols.size else m


def fit_letters(text: str, max_w: int, max_h: int) -> np.ndarray:
    """The text as a bool mask, as large as fits in max_w x max_h."""
    lo, hi = 6, max(8, max_h * 2)
    best = _letters(text, lo)
    while lo <= hi:  # largest font size that fits
        mid = (lo + hi) // 2
        m = _letters(text, mid)
        if m.shape[1] <= max_w and m.shape[0] <= max_h:
            best, lo = m, mid + 1
        else:
            hi = mid - 1
    return best


def plate_span(mask: np.ndarray) -> tuple[int, int]:
    """Columns the plate covers: the design's lowest row (its base bar) when that is wide enough,
    else the middle 70%."""
    h, w = mask.shape
    cols = np.flatnonzero(mask[-1])
    if cols.size and cols[-1] - cols[0] + 1 >= 0.5 * w:
        return int(cols[0]), int(cols[-1]) + 1
    return int(w * 0.15), int(w * 0.85)


def add_plate(mask: np.ndarray, text: str, params: cutcheck.Params) -> np.ndarray:
    """The design (cropped, as the check uses it) with the name plate added below. Rows above the plate
    are the design unchanged, so edits of the design map one to one."""
    text = " ".join(str(text or "").split())
    if not text:
        return mask
    h, w = mask.shape
    x0, x1 = plate_span(mask)
    letters = fit_letters(text, int((x1 - x0) * TEXT_FILL), max(8, int(h * LETTER_FRAC)))
    top, bottom = max(4, int(letters.shape[0] * PAD_TOP)), max(4, int(letters.shape[0] * PAD_BOTTOM))
    plate_h = letters.shape[0] + top + bottom
    out = np.zeros((h + plate_h, w), dtype=bool)
    out[:h] = mask
    out[h - 1:, x0:x1] = True  # overlaps the design's last row: one piece
    ly, lx = h + top, x0 + (x1 - x0 - letters.shape[1]) // 2
    out[ly:ly + letters.shape[0], lx:lx + letters.shape[1]] &= ~letters
    return _bridge_counters(out, h, params)


def _bridge_counters(out: np.ndarray, plate_top: int, params: cutcheck.Params) -> np.ndarray:
    """Every loose piece inside the plate (a letter's counter) is tied to the plate like a stencil font:
    a vertical bar through the letter's stroke, up or down, whichever is shorter, at the counter's middle."""
    lab, n = ndimage.label(out, structure=cutcheck.FOUR)
    if n < 2:
        return out
    sizes = ndimage.sum(out, lab, range(1, n + 1))
    main = int(np.argmax(sizes)) + 1
    ppm = out.shape[1] / params.width_mm
    result = out.copy()
    for i, sl in enumerate(ndimage.find_objects(lab), start=1):
        if i == main or sl is None or sl[0].start < plate_top:
            continue  # the portrait's own loose parts are the user's call (fix cards)
        piece = lab == i
        ys, xs = np.nonzero(piece)
        cx = int(round(xs.mean()))
        width = max((params.min_width_mm + 1.0) * ppm, 0.3 * (xs.max() - xs.min() + 1))
        width = min(width, 0.6 * (xs.max() - xs.min() + 1))  # a slim tie, never wider than the counter
        best = None
        for step in (-1, 1):  # up through the stroke above, or down through the stroke below
            col = piece[:, cx]
            if not col.any():
                continue
            y = int(np.flatnonzero(col)[0 if step < 0 else -1])
            start, dist = y, 0
            y += step
            while 0 <= y < out.shape[0] and not out[y, cx]:
                y += step
                dist += 1
            if 0 <= y < out.shape[0] and lab[y, cx] == main and (best is None or dist < best[0]):
                best = (dist, start, y)
        if best is None:
            continue
        _, y0, y1 = best
        x0, x1 = int(cx - width / 2), int(cx + width / 2) + 1
        result[min(y0, y1):max(y0, y1) + 1, x0:x1] = True
    return result
