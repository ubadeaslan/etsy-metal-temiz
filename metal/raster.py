"""Turn an AI/uploaded image into a clean boolean metal mask (True = metal stays)."""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

WORK_EDGE = 2400  # long edge of the working mask in px
FOUR = ndimage.generate_binary_structure(2, 1)


def open_image(source: Path | bytes) -> Image.Image:
    img = Image.open(io.BytesIO(source) if isinstance(source, bytes) else source)
    img.load()
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        white = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(white, img)
    return img.convert("L")


def _otsu(gray: np.ndarray) -> float:
    hist, edges = np.histogram(gray, bins=256, range=(0.0, 1.0))
    hist = hist.astype(np.float64)
    total = hist.sum()
    if total == 0:
        return 0.5
    centers = (edges[:-1] + edges[1:]) / 2
    weight_bg = np.cumsum(hist)
    weight_fg = total - weight_bg
    mean_cum = np.cumsum(hist * centers)
    mean_total = mean_cum[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        between = (mean_total * weight_bg - mean_cum) ** 2 / (weight_bg * weight_fg)
    between = np.nan_to_num(between)
    return float(np.clip(centers[int(np.argmax(between))], 0.25, 0.75))


def binarize(img: Image.Image, long_edge: int = WORK_EDGE) -> np.ndarray:
    scale = long_edge / max(img.size)
    size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
    img = img.resize(size, Image.LANCZOS)
    gray = np.asarray(img, dtype=np.float32) / 255.0
    gray = ndimage.gaussian_filter(gray, sigma=max(0.6, scale * 0.5))
    mask = gray < _otsu(gray)
    border = np.concatenate([mask[0], mask[-1], mask[:, 0], mask[:, -1]])
    if border.mean() > 0.5:  # white design on black background: invert
        mask = ~mask
    return mask


def remove_specks(mask: np.ndarray, min_px: float, min_hole_px: float | None = None) -> np.ndarray:
    """Drop metal specks smaller than min_px and fill pinholes smaller than min_hole_px (areas; the
    pinhole limit defaults to min_px)."""
    mask = mask.copy()
    for target in (True, False):
        region = mask if target else ~mask
        lab, n = ndimage.label(region, structure=FOUR)
        if n == 0:
            continue
        sizes = ndimage.sum(region, lab, range(1, n + 1))
        small = np.zeros(n + 1, dtype=bool)
        small[1:] = sizes < (min_px if target or min_hole_px is None else min_hole_px)
        if not target:  # never "fill" the outside background
            for edge in (lab[0], lab[-1], lab[:, 0], lab[:, -1]):
                small[np.unique(edge)] = False
        mask[small[lab]] = not target
    return mask


def crop(mask: np.ndarray) -> np.ndarray:
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    if rows.size == 0:
        raise ValueError("görselde metal (siyah) alan bulunamadı")
    return mask[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]


def prepare(source: Path | bytes) -> np.ndarray:
    mask = binarize(open_image(source))
    mask = remove_specks(mask, min_px=mask.size * 2e-6 + 4)
    return crop(mask)


def to_image(mask: np.ndarray) -> Image.Image:
    """Metal black on white, 8-bit."""
    return Image.fromarray(np.where(mask, 0, 255).astype(np.uint8), mode="L")


def load_mask(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("L")) < 128


def png_bytes(img: Image.Image, max_edge: int | None = None) -> bytes:
    if max_edge and max(img.size) > max_edge:
        img = img.copy()
        img.thumbnail((max_edge, max_edge), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
