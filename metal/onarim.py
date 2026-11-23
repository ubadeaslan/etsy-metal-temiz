"""Fixes for what the cut check marks, worked out on the cut mask itself (no AI; the design stays as drawn).

Every marked spot gets a few options and one is picked automatically:
  ADA     floating part: extend the design's own protrusions that point at it (from both sides when there
          are two, e.g. the tick marks either side of a clock numeral), shift it onto the main piece (picked
          only when it is almost touching), the shortest bridge, or delete it
  KOPRU   thin link between two parts: thicken it to the minimum width
  UC      thin tip: thicken it, or cut it off
  DELIK   small hole: enlarge it to the minimum diameter, or fill it
  BOSLUK  narrow gap: open it to the minimum gap, or fill the narrow part
An option is a change inside a window around the spot (metal added / removed), so many can be combined.
"""
from __future__ import annotations

import base64
import io
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

from . import cutcheck

FOUR = cutcheck.FOUR
JOINT_MM = 4.0         # new bridges and extensions: over the 3 mm minimum, so they pass with margin
SPIKE_MM = 4.0         # main-body features narrower than 2 x this count as protrusions (tick marks, stubs)
REACH_MM = 12.0        # how far a protrusion may be extended to reach a floating part
SHIFT_AUTO_MM = 2.0    # a move this small goes unnoticed; larger moves are offered, never picked
SHIFT_MAX_MM = 8.0     # overlap tried beyond touching
MAX_CARDS = 24         # cards per finding type; the rest are still fixed by "all automatic"
TILE = 220             # preview tile edge in px

OPTIONS = {
    "ADA": [("uzat", "Uzat"), ("kopru", "Köprü"), ("kaydir", "Kaydır"), ("sil", "Sil")],
    "KOPRU": [("kalin", "Kalınlaştır")],
    "UC": [("kalin", "Kalınlaştır"), ("sil", "Kes")],
    "DELIK": [("buyut", "Büyüt"), ("kapat", "Kapat")],
    "BOSLUK": [("ac", "Aç"), ("kapat", "Kapat")],
}
TITLES = {"ADA": "Kopan parçalar", "KOPRU": "İnce köprüler", "UC": "İnce uçlar", "DELIK": "Küçük delikler",
          "BOSLUK": "Dar boşluklar"}
PREFIX = {"ADA": "P", "KOPRU": "K", "UC": "U", "DELIK": "D", "BOSLUK": "B"}
ORDER = list(OPTIONS)

BG, METAL = (250, 250, 248), (60, 64, 70)
ADDED, REMOVED = (46, 160, 67), (244, 170, 165)


@dataclass
class Fix:
    ok: bool
    note: str = ""
    win: tuple[slice, slice] | None = None
    add: np.ndarray | None = None      # bool, window-sized: metal added
    remove: np.ndarray | None = None   # bool, window-sized: metal taken away

    def apply(self, mask: np.ndarray) -> np.ndarray:
        out = mask.copy()
        if self.ok:
            region = out[self.win]  # a view: the window is changed in place
            if self.remove is not None:
                region &= ~self.remove
            if self.add is not None:
                region |= self.add
        return out


def _no(note: str) -> Fix:
    return Fix(False, note)


class Scene:
    """The checked mask with its scale, and the part labels (computed once, on demand)."""

    def __init__(self, mask: np.ndarray, params: cutcheck.Params):
        self.mask = mask
        self.p = params
        self.ppm = mask.shape[1] / params.width_mm
        self.joint = max(JOINT_MM, params.min_width_mm + 1.0) * self.ppm
        self._labels: tuple[np.ndarray, int] | None = None

    def px(self, mm: float) -> float:
        return mm * self.ppm

    @property
    def labels(self) -> tuple[np.ndarray, int]:
        if self._labels is None:
            lab, n = ndimage.label(self.mask, structure=FOUR)
            sizes = ndimage.sum(self.mask, lab, range(1, n + 1)) if n else np.array([])
            self._labels = (lab, int(np.argmax(sizes)) + 1 if n else 0)
        return self._labels

    def window(self, sl: tuple[slice, slice], margin_mm: float) -> tuple[slice, slice]:
        pad = int(math.ceil(self.px(margin_mm)))
        h, w = self.mask.shape
        return (slice(max(0, sl[0].start - pad), min(h, sl[0].stop + pad)),
                slice(max(0, sl[1].start - pad), min(w, sl[1].stop + pad)))

    def is_full(self, win: tuple[slice, slice]) -> bool:
        h, w = self.mask.shape
        return win[0].start == 0 and win[1].start == 0 and win[0].stop == h and win[1].stop == w


def paste(dst: tuple[slice, slice], src: tuple[slice, slice], arr: np.ndarray) -> np.ndarray:
    """arr (laid out over window src) re-cut to window dst; zeros where they do not overlap."""
    out = np.zeros((dst[0].stop - dst[0].start, dst[1].stop - dst[1].start), dtype=bool)
    y0, y1 = max(dst[0].start, src[0].start), min(dst[0].stop, src[0].stop)
    x0, x1 = max(dst[1].start, src[1].start), min(dst[1].stop, src[1].stop)
    if y0 < y1 and x0 < x1:
        out[y0 - dst[0].start:y1 - dst[0].start, x0 - dst[1].start:x1 - dst[1].start] = \
            arr[y0 - src[0].start:y1 - src[0].start, x0 - src[1].start:x1 - src[1].start]
    return out


def _bar(shape: tuple[int, int], p, q, width: float) -> np.ndarray:
    """Round-capped bar from p to q, points as (y, x)."""
    img = Image.new("L", (shape[1], shape[0]), 0)
    draw = ImageDraw.Draw(img)
    draw.line([(p[1], p[0]), (q[1], q[0])], fill=255, width=max(1, round(width)))
    r = width / 2
    for y, x in (p, q):
        draw.ellipse((x - r, y - r, x + r, y + r), fill=255)
    return np.asarray(img) > 127


def _joined(scene: Scene, m: np.ndarray, a: np.ndarray, b: np.ndarray) -> bool:
    """Is a still attached to b once everything thinner than the minimum width is taken away?"""
    opened = cutcheck.disk_open(m, scene.p.min_width_mm / 2 * scene.ppm)
    lab, _ = ndimage.label(opened, structure=FOUR)
    la, lb = np.unique(lab[a & opened]), np.unique(lab[b & opened])
    return bool(set(la[la > 0]) & set(lb[lb > 0]))


def _region(item: dict, win: tuple[slice, slice]) -> np.ndarray:
    return paste(win, item["sl"], item["region"])


def ref_pixel(item: dict) -> tuple[int, int]:
    """A pixel inside the spot: finds the same spot again after a fresh check of the same mask."""
    ys, xs = np.nonzero(item["region"])
    return int(item["sl"][0].start + ys[0]), int(item["sl"][1].start + xs[0])


def area_mm2(scene: Scene, item: dict) -> float:
    return float(item["region"].sum()) / scene.ppm ** 2


# --- floating parts ---------------------------------------------------------------------------------

@dataclass
class Island:
    win: tuple[slice, slice]
    m: np.ndarray        # mask in the window
    main: np.ndarray     # the main piece in the window
    part: np.ndarray     # the floating part in the window
    near: tuple[int, int]
    target: tuple[int, int]
    gap: float           # px


def _island(scene: Scene, item: dict) -> Island:
    lab, main = scene.labels
    margin = 30.0
    while True:
        win = scene.window(item["sl"], margin)
        main_w = lab[win] == main
        if main_w.any():
            part = _region(item, win)
            dist, idx = ndimage.distance_transform_edt(~main_w, return_indices=True)
            d = np.where(part, dist, np.inf)
            py, px = np.unravel_index(int(np.argmin(d)), d.shape)
            gap = float(dist[py, px])
            # a closer piece of the main part could lie outside a window this tight: widen and redo
            if gap <= scene.px(margin) or scene.is_full(win):
                return Island(win, scene.mask[win], main_w, part, (int(py), int(px)),
                              (int(idx[0][py, px]), int(idx[1][py, px])), gap)
            margin = gap / scene.ppm + 10
        elif scene.is_full(win):
            raise ValueError("ana parça bulunamadı")
        else:
            margin *= 2


def _bridge(scene: Scene, isl: Island) -> Fix:
    (py, px), (qy, qx) = isl.near, isl.target
    v = np.array([qy - py, qx - px], dtype=float)
    length = float(np.linalg.norm(v))
    if length == 0:
        return _no("zaten değiyor")
    v /= length
    reach = scene.joint * 0.6  # run into both parts so the joint is solid
    bar = _bar(isl.m.shape, (py - v[0] * reach, px - v[1] * reach), (qy + v[0] * reach, qx + v[1] * reach), scene.joint)
    return Fix(True, f"{isl.gap / scene.ppm:.1f} mm", isl.win, add=bar & ~isl.m)


def _shift(scene: Scene, isl: Island) -> tuple[Fix, float | None]:
    (py, px), (qy, qx) = isl.near, isl.target
    v = np.array([qy - py, qx - px], dtype=float)
    length = float(np.linalg.norm(v))
    if length == 0:
        return _no("zaten değiyor"), None
    v /= length
    rest = isl.m & ~isl.part
    ys, xs = np.nonzero(isl.part)
    h, w = isl.m.shape
    for extra in np.arange(0.5, SHIFT_MAX_MM + 0.01, 0.5):
        s = length + scene.px(extra)
        dy, dx = int(round(v[0] * s)), int(round(v[1] * s))
        ys2, xs2 = ys + dy, xs + dx
        if ys2.min() < 0 or xs2.min() < 0 or ys2.max() >= h or xs2.max() >= w:
            break
        moved = np.zeros_like(isl.part)
        moved[ys2, xs2] = True
        if _joined(scene, rest | moved, moved, isl.main & rest):
            mm = s / scene.ppm
            return Fix(True, f"{mm:.1f} mm", isl.win, add=moved & ~isl.m, remove=isl.part & ~moved), mm
    return _no("değdirilemedi"), None


def _extend(scene: Scene, isl: Island) -> Fix:
    """The main piece's own protrusions that point at the part, grown along their own line, at their own
    thickness, until they run into it. Two tick marks either side of a numeral both grow: no leaning."""
    spikes = isl.main & ~cutcheck.disk_open(isl.main, scene.px(SPIKE_MM))
    reach = scene.px(REACH_MM)
    dist = ndimage.distance_transform_edt(~isl.part)
    # a protrusion counts when it comes within reach; its direction is read over a longer stretch of it
    lab, n = ndimage.label(spikes & (dist <= reach + scene.px(10)), structure=FOUR)
    if not n:
        return _no("çıkıntı yok")
    near = dist <= reach
    inside = ndimage.distance_transform_edt(isl.main)
    py, px = np.nonzero(isl.part)
    target = np.array([py.mean(), px.mean()])
    h, w = isl.m.shape
    add = np.zeros_like(isl.m)
    used = 0
    for k in range(1, n + 1):
        comp = lab == k
        if not (comp & near).any():
            continue
        sy, sx = np.nonzero(comp)
        if len(sy) < 4 * scene.ppm ** 2:  # a sliver at a corner, not a protrusion
            continue
        pts = np.column_stack([sy, sx]).astype(float)
        c = pts.mean(axis=0)
        ev, vecs = np.linalg.eigh(np.cov((pts - c).T))
        if ev.max() < 2.25 * max(ev.min(), 1e-6):  # not elongated: no direction to grow in
            continue
        u = vecs[:, int(np.argmax(ev))]
        if np.dot(target - c, u) < 0:
            u = -u
        along = (pts - c) @ u
        tip = pts[int(np.argmax(along))]
        end = along >= along.max() - scene.px(3)  # thickness measured at the end that grows
        width = max(scene.joint, 2 * float(np.percentile(inside[sy[end], sx[end]], 90)))
        hit = None
        for step in range(1, int(reach) + 1):
            y, x = (tip + u * step).round().astype(int)
            if not (0 <= y < h and 0 <= x < w):
                break
            if isl.part[y, x]:
                hit = tip + u * (step + width * 0.6)
                break
            if isl.m[y, x] and step > 2:  # some other metal is in the way
                break
        if hit is None:
            continue
        add |= _bar(isl.m.shape, tuple(tip - u * width * 0.5), tuple(hit), width)
        used += 1
    if not used:
        return _no("çıkıntı yok")
    if not _joined(scene, isl.m | add, isl.part, isl.main):
        return _no("bağlanmadı")
    return Fix(True, "iki taraftan" if used > 1 else "tek taraftan", isl.win, add=add & ~isl.m)


def _island_fixes(scene: Scene, item: dict) -> tuple[dict[str, Fix], str, str]:
    isl = _island(scene, item)
    shift, shift_mm = _shift(scene, isl)
    fixes = {
        "uzat": _extend(scene, isl),
        "kopru": _bridge(scene, isl),
        "kaydir": shift,
        "sil": Fix(True, "", isl.win, remove=isl.part.copy()),
    }
    if fixes["uzat"].ok:
        auto = "uzat"
    elif shift_mm is not None and shift_mm <= SHIFT_AUTO_MM:
        auto = "kaydir"
    else:
        auto = "kopru"
    detail = f"{area_mm2(scene, item):.0f} mm² · ana parçaya {isl.gap / scene.ppm:.1f} mm"
    return fixes, auto, detail


# --- thin links and tips ----------------------------------------------------------------------------

def _thicken(scene: Scene, item: dict) -> tuple[Fix, float]:
    win = scene.window(item["sl"], scene.p.min_width_mm * 2 + 2)
    m = scene.mask[win]
    part = _region(item, win) & m
    inside = ndimage.distance_transform_edt(m)
    half = float(inside[part].max()) if part.any() else 0.0
    target = scene.p.min_width_mm / 2 * 1.15 * scene.ppm
    grow = max(1.0, target - half + 0.5)
    add = (ndimage.distance_transform_edt(~part) <= grow) & ~m
    now_mm = 2 * half / scene.ppm
    return Fix(True, f"{now_mm:.1f} → {2 * (half + grow) / scene.ppm:.1f} mm", win, add=add), now_mm


def _thin_fixes(scene: Scene, item: dict) -> tuple[dict[str, Fix], str, str]:
    thick, now_mm = _thicken(scene, item)
    fixes = {"kalin": thick}
    if item["code"] == "UC":
        win = scene.window(item["sl"], 1)
        fixes["sil"] = Fix(True, "", win, remove=_region(item, win) & scene.mask[win])
    return fixes, "kalin", f"en ince yeri ~{now_mm:.1f} mm"


# --- holes and gaps ---------------------------------------------------------------------------------

def _hole_fixes(scene: Scene, item: dict) -> tuple[dict[str, Fix], str, str]:
    win = scene.window(item["sl"], scene.p.min_hole_mm + 3)
    m = scene.mask[win]
    hole = _region(item, win)
    ys, xs = np.nonzero(hole)
    r = scene.p.min_hole_mm / 2 * 1.15 * scene.ppm
    yy, xx = np.ogrid[:m.shape[0], :m.shape[1]]
    disk = (yy - ys.mean()) ** 2 + (xx - xs.mean()) ** 2 <= r * r
    diameter = 2 * math.sqrt(area_mm2(scene, item) / math.pi)
    fixes = {
        "buyut": Fix(True, f"Ø{2 * r / scene.ppm:.1f} mm", win, remove=disk & m),
        "kapat": Fix(True, "", win, add=hole.copy()),
    }
    auto = "buyut" if diameter >= 0.5 * scene.p.min_hole_mm else "kapat"
    return fixes, auto, f"Ø~{diameter:.1f} mm"


def _gap_fixes(scene: Scene, item: dict) -> tuple[dict[str, Fix], str, str]:
    win = scene.window(item["sl"], scene.p.min_gap_mm * 2 + 3)
    m = scene.mask[win]
    gap = _region(item, win) & ~m
    half = float(ndimage.distance_transform_edt(~m)[gap].max()) if gap.any() else 0.0
    target = scene.p.min_gap_mm / 2 * 1.15 * scene.ppm
    grow = max(1.0, target - half + 0.5)
    fixes = {
        "ac": Fix(True, f"{2 * (half + grow) / scene.ppm:.1f} mm", win,
                  remove=(ndimage.distance_transform_edt(~gap) <= grow) & m),
        "kapat": Fix(True, "", win, add=gap.copy()),
    }
    # a short narrow spot is the tip of a wedge where two shapes meet: filling it is invisible.
    # A long one is a slit drawn on purpose: open it up instead.
    length_mm = max(item["sl"][0].stop - item["sl"][0].start, item["sl"][1].stop - item["sl"][1].start) / scene.ppm
    auto = "kapat" if length_mm <= 4 * scene.p.min_gap_mm else "ac"
    return fixes, auto, f"en dar yeri ~{2 * half / scene.ppm:.1f} mm · {length_mm:.0f} mm boyunca"


def fixes_for(scene: Scene, item: dict) -> tuple[dict[str, Fix], str, str]:
    """All options for one marked spot, the automatic pick and a one-line description."""
    code = item["code"]
    if code == "ADA":
        return _island_fixes(scene, item)
    if code in ("KOPRU", "UC"):
        return _thin_fixes(scene, item)
    if code == "DELIK":
        return _hole_fixes(scene, item)
    return _gap_fixes(scene, item)


# --- what the panel calls ---------------------------------------------------------------------------

def ordered(res: cutcheck.Result) -> list[dict]:
    """Marked spots in card order: by type, then top to bottom, left to right."""
    return sorted(res.items, key=lambda it: (ORDER.index(it["code"]), it["sl"][0].start, it["sl"][1].start))


def find(res: cutcheck.Result, code: str, ref: tuple[int, int]) -> dict | None:
    y, x = ref
    for it in res.items:
        sl = it["sl"]
        if it["code"] == code and sl[0].start <= y < sl[0].stop and sl[1].start <= x < sl[1].stop \
                and it["region"][y - sl[0].start, x - sl[1].start]:
            return it
    return None


def apply_option(mask: np.ndarray, params: cutcheck.Params, res: cutcheck.Result, code: str,
                 ref: tuple[int, int], key: str) -> tuple[np.ndarray, str]:
    item = find(res, code, ref)
    if item is None:
        raise ValueError("Bu sorun artık yok — sayfa güncel değil, yenile.")
    fixes, _, _ = fixes_for(Scene(mask, params), item)
    fix = fixes.get(key)
    if fix is None or not fix.ok:
        raise ValueError("Bu düzeltme bu noktada uygulanamıyor" + (f" ({fix.note})." if fix else "."))
    return fix.apply(mask), dict(OPTIONS[code])[key]


def apply_auto(mask: np.ndarray, params: cutcheck.Params, res: cutcheck.Result,
               codes: list[str] | None = None, skip_from: int | None = None) -> tuple[np.ndarray, int]:
    """Every marked spot (of the given types) fixed with its automatic pick. Each fix is worked out on the
    same mask and the changes are combined; where they overlap, added metal wins. Spots starting at row
    skip_from or below (a name plate drawn by code) are left alone."""
    scene = Scene(mask, params)
    add = np.zeros_like(mask)
    remove = np.zeros_like(mask)
    done = 0
    for item in ordered(res):
        if codes and item["code"] not in codes:
            continue
        if skip_from is not None and item["sl"][0].start >= skip_from:
            continue
        try:
            fixes, auto, _ = fixes_for(scene, item)
        except ValueError:
            continue
        fix = fixes[auto]
        if not fix.ok:
            continue
        if fix.add is not None:
            add[fix.win] |= fix.add
        if fix.remove is not None:
            remove[fix.win] |= fix.remove
        done += 1
    return (mask & ~remove) | add, done


def _tile(scene: Scene, sl: tuple[slice, slice], color=None, region=None, fix: Fix | None = None) -> Image.Image:
    h, w = scene.mask.shape
    cy, cx = (sl[0].start + sl[0].stop) / 2, (sl[1].start + sl[1].stop) / 2
    half = max(max(sl[0].stop - sl[0].start, sl[1].stop - sl[1].start) / 2 + scene.px(10), scene.px(14))
    half = min(half, max(h, w) / 2)
    tw = (slice(max(0, int(cy - half)), min(h, int(cy + half) + 1)), slice(max(0, int(cx - half)), min(w, int(cx + half) + 1)))
    base = scene.mask[tw]
    rgb = np.empty(base.shape + (3,), dtype=np.uint8)
    if fix is not None and fix.ok:
        add = paste(tw, fix.win, fix.add) if fix.add is not None else np.zeros_like(base)
        rem = paste(tw, fix.win, fix.remove) if fix.remove is not None else np.zeros_like(base)
        new = (base & ~rem) | add
        rgb[:] = BG
        rgb[new] = METAL
        rgb[rem & ~new] = REMOVED
        rgb[add & ~base] = ADDED
    else:
        rgb[:] = BG
        rgb[base] = METAL
        if region is not None:
            rgb[paste(tw, sl, region)] = color
    img = Image.fromarray(rgb)
    side = max(img.size)
    square = Image.new("RGB", (side, side), BG)  # spots at the design's edge: keep the tile square
    square.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
    return square.resize((TILE, TILE), Image.LANCZOS)


def analyze(mask: np.ndarray, params: cutcheck.Params, res: cutcheck.Result, out_dir: Path, rel: str,
            skip_from: int | None = None) -> dict:
    """Option cards for the marked spots, with preview tiles written to out_dir (named rel/...). Spots
    starting at row skip_from or below (a name plate drawn by code) get no card."""
    scene = Scene(mask, params)
    out_dir.mkdir(parents=True, exist_ok=True)
    groups = []
    items = [it for it in ordered(res) if skip_from is None or it["sl"][0].start < skip_from]
    for code in ORDER:
        spots = [it for it in items if it["code"] == code]
        if not spots:
            continue
        cards = []
        for n, item in enumerate(spots[:MAX_CARDS], start=1):
            label = f"{PREFIX[code]}{n}"
            try:
                fixes, auto, detail = fixes_for(scene, item)
            except ValueError:
                continue
            once = f"{label}-once.png"
            _tile(scene, item["sl"], cutcheck.COLORS[code], item["region"]).save(out_dir / once)
            options = []
            for key, title in OPTIONS[code]:
                fix = fixes[key]
                tile = ""
                if fix.ok:
                    tile = f"{rel}/{label}-{key}.png"
                    _tile(scene, item["sl"], fix=fix).save(out_dir / f"{label}-{key}.png")
                options.append({"key": key, "label": title, "ok": fix.ok, "note": fix.note, "tile": tile})
            sl = item["sl"]
            cards.append({
                "code": code, "label": label, "level": item["level"], "detail": detail, "auto": auto,
                "ref": list(ref_pixel(item)), "bbox": [sl[0].start, sl[1].start, sl[0].stop, sl[1].stop],
                "tile": f"{rel}/{once}", "options": options,
            })
        groups.append({
            "code": code, "title": TITLES[code], "count": len(spots), "cards": cards,
            "level": cutcheck.HATA if any(it["level"] == cutcheck.HATA for it in spots) else cutcheck.UYARI,
        })
    return {"groups": groups}


def label_overlay(img: Image.Image, mask_shape: tuple[int, int], fixes: dict, font) -> Image.Image:
    """Write the card labels (P1, B3, ...) next to their circles on the check picture."""
    scale = img.width / mask_shape[1]
    draw = ImageDraw.Draw(img)
    for group in fixes.get("groups", []):
        color = cutcheck.COLORS[group["code"]]
        for card in group["cards"]:
            y0, x0, y1, x1 = card["bbox"]
            cx, cy = (x0 + x1) / 2 * scale, (y0 + y1) / 2 * scale
            rad = max(x1 - x0, y1 - y0) / 2 * scale + 10
            draw.text((cx + rad * 0.72, cy - rad * 0.72), card["label"], font=font, fill=color, anchor="lb",
                      stroke_width=3, stroke_fill=(255, 255, 255))
    return img


def problem_layer(shape: tuple[int, int], res: cutcheck.Result, offset: tuple[int, int]) -> str:
    """Transparent PNG (data URL) the size of the editor's canvas with the problem pixels coloured."""
    rgba = np.zeros(shape + (4,), dtype=np.uint8)
    oy, ox = offset
    for code in ("UC", "BOSLUK", "DELIK", "KOPRU", "ADA"):
        layer = res.paint.get(code)
        if layer is None or not layer.any():
            continue
        view = rgba[oy:oy + layer.shape[0], ox:ox + layer.shape[1]]  # a name plate may reach past the canvas
        view[layer[:view.shape[0], :view.shape[1]]] = (*cutcheck.COLORS[code], 235)
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, "PNG", optimize=False, compress_level=1)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
