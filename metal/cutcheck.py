"""Cuttability check on a cropped metal mask at physical scale.

Findings:
  ADA      metal parts not attached to the main piece (fall out when cut)      HATA
  KOPRU    links thinner than min width that hold two thick regions together   HATA / UYARI
  UC       protrusions thinner than min width (bend, burn away)                UYARI
  DELIK    holes smaller than min hole diameter                                UYARI
  BOSLUK   white slots narrower than min gap (close up when cut)               UYARI
  ORAN     metal coverage too low / too high                                   UYARI
Plus stats: size, weight estimate, cut length estimate, pierce count.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

HATA, UYARI, BILGI = "HATA", "UYARI", "BİLGİ"
STEEL_G_PER_CM3 = 7.85
FOUR = ndimage.generate_binary_structure(2, 1)
EIGHT = ndimage.generate_binary_structure(2, 2)
BIG_PART_MM2 = 200.0  # a "thick region" worth holding: 2 cm²
PINHOLE_MM2 = 0.3     # holes under this (Ø ~0.6 mm) are dirt in the image, not design: filled silently
OVERLAY_EDGE = 1600

COLORS = {
    "bg": (250, 250, 248),
    "metal": (72, 76, 82),
    "ADA": (229, 57, 53),
    "KOPRU": (229, 57, 53),
    "UC": (251, 140, 0),
    "DELIK": (30, 136, 229),
    "BOSLUK": (142, 36, 170),
}


@dataclass
class Params:
    width_mm: float
    thickness_mm: float = 1.5
    min_width_mm: float = 3.0
    min_hole_mm: float = 4.0
    min_gap_mm: float = 2.0
    speck_mm2: float = 2.0
    multi_piece: bool = False


@dataclass
class Result:
    findings: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    marks: list[tuple[str, tuple[int, int, int, int]]] = field(default_factory=list)  # (code, bbox y0,x0,y1,x1)
    paint: dict = field(default_factory=dict)  # code -> bool mask
    items: list[dict] = field(default_factory=list)  # one per marked spot: code, level, sl (slices), region (bool in sl)

    @property
    def ok(self) -> bool:
        return not any(f["level"] == HATA for f in self.findings)

    def add(self, level: str, code: str, msg: str, count: int = 1) -> None:
        self.findings.append({"level": level, "code": code, "msg": msg, "count": count})


def disk_open(mask: np.ndarray, r_px: float, outside: bool = False) -> np.ndarray:
    """Morphological opening by a disk of radius r_px, via two distance transforms (fast for big r).

    The mask is padded with `outside` first so the crop edge does not fake thin parts or narrow gaps.
    """
    if r_px < 0.75:
        return mask.copy()
    pad = int(math.ceil(r_px * 2)) + 2
    padded = np.pad(mask, pad, constant_values=outside)
    centers = ndimage.distance_transform_edt(padded) >= r_px
    if not centers.any():
        return np.zeros_like(mask)
    opened = (ndimage.distance_transform_edt(~centers) <= r_px) & padded
    return opened[pad:-pad, pad:-pad]


def _bbox(sl: tuple[slice, slice]) -> tuple[int, int, int, int]:
    return sl[0].start, sl[1].start, sl[0].stop, sl[1].stop


def _grow(sl: tuple[slice, slice], pad: int, shape: tuple[int, int]) -> tuple[slice, slice]:
    return (slice(max(0, sl[0].start - pad), min(shape[0], sl[0].stop + pad)),
            slice(max(0, sl[1].start - pad), min(shape[1], sl[1].stop + pad)))


def remove_specks_mm(mask: np.ndarray, px_per_mm: float, speck_mm2: float) -> np.ndarray:
    """Metal specks under speck_mm2 go (they would fall out). Holes are the design's own (the stars of a
    flag): only pinholes no cutter can make are filled; small real holes stay and the check reports them."""
    from .raster import remove_specks
    return remove_specks(mask, speck_mm2 * px_per_mm ** 2, PINHOLE_MM2 * px_per_mm ** 2)


def check(mask: np.ndarray, p: Params) -> Result:
    res = Result()
    h, w = mask.shape
    ppm = w / p.width_mm
    mm2 = 1 / ppm ** 2

    # --- islands --------------------------------------------------------------------------------
    lab, n = ndimage.label(mask, structure=FOUR)
    sizes = ndimage.sum(mask, lab, range(1, n + 1)) if n else np.array([])
    main = int(np.argmax(sizes)) + 1 if n else 0
    islands = [i for i in range(1, n + 1) if i != main]
    if islands:
        island_mask = mask & (lab != main)
        objs = ndimage.find_objects(lab)
        for i in islands:
            res.marks.append(("ADA", _bbox(objs[i - 1])))
            res.items.append({"code": "ADA", "level": UYARI if p.multi_piece else HATA, "sl": objs[i - 1],
                              "region": lab[objs[i - 1]] == i})
        res.paint["ADA"] = island_mask
        area = float(island_mask.sum()) * mm2
        if p.multi_piece:
            res.add(UYARI, "ADA", f"{len(islands)} ayrı parça (çok parçalı set olarak işaretli) — toplam {area:.0f} mm²", len(islands))
        else:
            res.add(HATA, "ADA", f"Ana parçaya bağlı olmayan {len(islands)} parça kesimde düşer "
                                 f"(toplam {area:.0f} mm²). Köprüyle bağla ya da sil.", len(islands))

    # --- thin bridges and tips ------------------------------------------------------------------
    r = p.min_width_mm / 2 * ppm
    opened = disk_open(mask, r)
    thin = mask & ~opened
    lab_o, n_o = ndimage.label(opened, structure=FOUR)
    area_o = ndimage.sum(opened, lab_o, range(1, n_o + 1)) * mm2 if n_o else np.array([])
    lab_t, n_t = ndimage.label(thin, structure=EIGHT)
    bridge_hard = bridge_soft = tips = 0
    bridge_mask = np.zeros_like(mask)
    tip_mask = np.zeros_like(mask)
    pad = 3
    for k, sl in enumerate(ndimage.find_objects(lab_t), start=1):
        if sl is None:
            continue
        g = _grow(sl, pad, mask.shape)
        region = lab_t[g] == k
        touched = np.unique(lab_o[g][ndimage.binary_dilation(region, structure=EIGHT, iterations=pad)])
        touched = touched[touched > 0]
        if len(touched) >= 2:
            big = int((area_o[touched - 1] >= BIG_PART_MM2).sum())
            bridge_mask[g] |= region
            res.marks.append(("KOPRU", _bbox(sl)))
            res.items.append({"code": "KOPRU", "level": HATA if big >= 2 else UYARI, "sl": g, "region": region})
            if big >= 2:
                bridge_hard += 1
            else:
                bridge_soft += 1
        else:
            extent = max(sl[0].stop - sl[0].start, sl[1].stop - sl[1].start)
            if extent >= 2.5 * r:  # longer than a corner sliver: a real thin protrusion
                tip_mask[g] |= region
                tips += 1
                res.marks.append(("UC", _bbox(sl)))
                res.items.append({"code": "UC", "level": UYARI, "sl": g, "region": region})
    if bridge_hard:
        res.add(HATA, "KOPRU", f"{bridge_hard} köprü {p.min_width_mm:g} mm'den ince ve büyük parçaları "
                               f"birbirine tutuyor — kesimde/taşımada kırılır, kalınlaştır.", bridge_hard)
    if bridge_soft:
        res.add(UYARI, "KOPRU", f"{bridge_soft} küçük detay {p.min_width_mm:g} mm'den ince bir boyunla bağlı — eğilebilir.", bridge_soft)
    if tips:
        res.add(UYARI, "UC", f"{tips} uç/çizgi {p.min_width_mm:g} mm'den ince — yanabilir ya da eğilebilir.", tips)
    res.paint["KOPRU"] = bridge_mask
    res.paint["UC"] = tip_mask

    # --- holes and narrow gaps ------------------------------------------------------------------
    bg = ~mask
    lab_b, n_b = ndimage.label(bg, structure=FOUR)
    outside = set(np.unique(np.concatenate([lab_b[0], lab_b[-1], lab_b[:, 0], lab_b[:, -1]]))) - {0}
    hole_sizes = ndimage.sum(bg, lab_b, range(1, n_b + 1)) if n_b else np.array([])
    holes = [i for i in range(1, n_b + 1) if i not in outside]
    small_holes = []
    for i in holes:
        diameter = 2 * math.sqrt(hole_sizes[i - 1] * mm2 / math.pi)
        if diameter < p.min_hole_mm:
            small_holes.append(i)
    if small_holes:
        objs_b = ndimage.find_objects(lab_b)
        flags = np.zeros(n_b + 1, dtype=bool)
        flags[small_holes] = True
        res.paint["DELIK"] = flags[lab_b]
        for i in small_holes:
            res.marks.append(("DELIK", _bbox(objs_b[i - 1])))
            res.items.append({"code": "DELIK", "level": UYARI, "sl": objs_b[i - 1], "region": lab_b[objs_b[i - 1]] == i})
        res.add(UYARI, "DELIK", f"{len(small_holes)} delik Ø{p.min_hole_mm:g} mm'den küçük — plazmada kapanabilir/yuvarlak çıkmaz.", len(small_holes))

    r_gap = p.min_gap_mm / 2 * ppm
    gap_space = bg.copy()
    if small_holes:
        gap_space &= ~res.paint["DELIK"]  # already reported
    narrow = gap_space & ~disk_open(gap_space, r_gap, outside=True)
    lab_g, _ = ndimage.label(narrow, structure=EIGHT)
    gaps = 0
    gap_mask = np.zeros_like(mask)
    for k, sl in enumerate(ndimage.find_objects(lab_g), start=1):
        if sl is None:
            continue
        extent = max(sl[0].stop - sl[0].start, sl[1].stop - sl[1].start)
        if extent >= 3 * r_gap:
            gap_mask[sl] |= lab_g[sl] == k
            gaps += 1
            res.marks.append(("BOSLUK", _bbox(sl)))
            res.items.append({"code": "BOSLUK", "level": UYARI, "sl": sl, "region": lab_g[sl] == k})
    if gaps:
        res.add(UYARI, "BOSLUK", f"{gaps} boşluk/yarık {p.min_gap_mm:g} mm'den dar — kesimde kapanabilir.", gaps)
    res.paint["BOSLUK"] = gap_mask

    # --- coverage and stats ---------------------------------------------------------------------
    metal_mm2 = float(mask.sum()) * mm2
    coverage = float(mask.mean())
    if coverage < 0.12:
        res.add(UYARI, "ORAN", f"Metal oranı %{coverage * 100:.0f} — çok narin, duvarda eğilebilir.")
    elif coverage > 0.75:
        res.add(UYARI, "ORAN", f"Metal oranı %{coverage * 100:.0f} — çok dolu; ağır ve detay okunmaz.")
    transitions = int((mask[:, 1:] != mask[:, :-1]).sum() + (mask[1:] != mask[:-1]).sum())
    transitions += int(mask[0].sum() + mask[-1].sum() + mask[:, 0].sum() + mask[:, -1].sum())
    cut_m = transitions * (math.pi / 4) / ppm / 1000
    weight_kg = metal_mm2 / 100 * (p.thickness_mm / 10) * STEEL_G_PER_CM3 / 1000
    res.stats = {
        "width_mm": round(p.width_mm, 1),
        "height_mm": round(h / ppm, 1),
        "metal_coverage": round(coverage, 3),
        "metal_cm2": round(metal_mm2 / 100, 1),
        "weight_kg_steel": round(weight_kg, 2),
        "cut_length_m": round(cut_m, 1),
        "pierces": len(holes) + 1 + len(islands),
        "parts": max(n, 0),
        "px_per_mm": round(ppm, 3),
    }
    res.add(BILGI, "OLCU", f"{p.width_mm / 25.4:.1f} × {h / ppm / 25.4:.1f} in ({p.width_mm / 10:.1f} × {h / ppm / 10:.1f} cm) · "
                           f"~{weight_kg:.2f} kg ({p.thickness_mm:g} mm çelik) · kesim boyu ~{cut_m:.1f} m · "
                           f"{res.stats['pierces']} delme")
    return res


def overlay(mask: np.ndarray, res: Result, max_edge: int = OVERLAY_EDGE) -> Image.Image:
    h, w = mask.shape
    rgb = np.empty((h, w, 3), dtype=np.uint8)
    rgb[:] = COLORS["bg"]
    rgb[mask] = COLORS["metal"]
    for code in ("UC", "BOSLUK", "DELIK", "KOPRU", "ADA"):
        layer = res.paint.get(code)
        if layer is not None and layer.any():
            rgb[layer] = COLORS[code]
    img = Image.fromarray(rgb)
    scale = min(1.0, max_edge / max(w, h))
    if scale < 1:
        img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    draw = ImageDraw.Draw(img)
    for code, (y0, x0, y1, x1) in res.marks[:400]:
        cx, cy = (x0 + x1) / 2 * scale, (y0 + y1) / 2 * scale
        rad = max((x1 - x0), (y1 - y0)) / 2 * scale + 10
        draw.ellipse((cx - rad, cy - rad, cx + rad, cy + rad), outline=COLORS[code], width=3)
    return img
