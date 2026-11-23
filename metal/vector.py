"""Metal mask -> SVG and DXF with real millimetre size (for the workshop's CAM / CNC machine)."""
from __future__ import annotations

import math
import re
from pathlib import Path

import ezdxf
import numpy as np
import vtracer
from ezdxf import units

from . import raster

Point = tuple[float, float]


def to_svg(mask: np.ndarray, width_mm: float) -> str:
    h, w = mask.shape
    svg = vtracer.convert_raw_image_to_svg(
        raster.png_bytes(raster.to_image(mask)), img_format="png", colormode="binary", mode="spline",
        filter_speckle=4, corner_threshold=60, length_threshold=4.0, max_iterations=10,
        splice_threshold=45, path_precision=2,
    )
    height_mm = h * width_mm / w
    header = (f'<svg version="1.1" xmlns="http://www.w3.org/2000/svg" '
              f'width="{width_mm:.2f}mm" height="{height_mm:.2f}mm" viewBox="0 0 {w} {h}">')
    svg = re.sub(r"<svg\b[^>]*>", header, svg, count=1)
    svg = svg.replace('fill="#000000"', 'fill="#000000" fill-rule="evenodd"')
    note = f"<!-- Etsy metal line: {width_mm:.1f} x {height_mm:.1f} mm, black = metal that stays -->"
    return svg.replace("-->\n", "-->\n" + note + "\n", 1)


# --- DXF ------------------------------------------------------------------------------------------
# The DXF holds the same outlines as the SVG: vtracer's bezier paths flattened to closed polylines.
# Units are millimetres ($INSUNITS = mm), the origin is the bottom-left corner, Y points up.

_TOKEN = re.compile(r"[MmLlHhVvCcQqZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_TRANSLATE = re.compile(r"translate\(\s*([-+\d.eE]+)[\s,]*([-+\d.eE]*)\s*\)")
LAYER = "KESIM"


def _flat(p0: Point, p1: Point, p2: Point, p3: Point, tol: float) -> bool:
    dx, dy = p3[0] - p0[0], p3[1] - p0[1]
    d = math.hypot(dx, dy)
    if d < 1e-9:
        return max(math.dist(p0, p1), math.dist(p0, p2)) <= tol
    return max(abs((p[0] - p0[0]) * dy - (p[1] - p0[1]) * dx) for p in (p1, p2)) / d <= tol


def _cubic(p0: Point, p1: Point, p2: Point, p3: Point, tol: float, out: list[Point], depth: int = 0) -> None:
    """Adaptive flattening: split (de Casteljau) until the control points lie within tol of the chord."""
    if depth >= 16 or _flat(p0, p1, p2, p3, tol):
        out.append(p3)
        return
    mid = lambda a, b: ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)  # noqa: E731
    p01, p12, p23 = mid(p0, p1), mid(p1, p2), mid(p2, p3)
    p012, p123 = mid(p01, p12), mid(p12, p23)
    p0123 = mid(p012, p123)
    _cubic(p0, p01, p012, p0123, tol, out, depth + 1)
    _cubic(p0123, p123, p23, p3, tol, out, depth + 1)


def svg_outlines(svg: str, tol: float = 0.1) -> tuple[list[list[Point]], float, float]:
    """Closed outlines of an SVG made by to_svg, in viewBox pixels (curves within tol px), + viewBox w, h."""
    _, _, w, h = map(float, re.search(r'viewBox="([^"]+)"', svg).group(1).replace(",", " ").split())
    loops: list[list[Point]] = []
    for tag in re.findall(r"<path\b[^>]*>", svg):
        found = re.search(r'\sd="([^"]*)"', tag)
        if not found:
            continue
        move = _TRANSLATE.search(tag)
        tx, ty = (float(move.group(1)), float(move.group(2) or 0)) if move else (0.0, 0.0)
        tokens = _TOKEN.findall(found.group(1))
        i, cmd = 0, ""
        cur = start = (0.0, 0.0)
        loop: list[Point] = []

        def num() -> float:
            nonlocal i
            i += 1
            return float(tokens[i - 1])

        def close() -> None:
            if len(loop) > 1 and math.dist(loop[0], loop[-1]) < 1e-6:
                loop.pop()
            if len(loop) >= 3:
                loops.append([(x + tx, y + ty) for x, y in loop])

        while i < len(tokens):
            if tokens[i].isalpha():
                cmd = tokens[i]
                i += 1
                if cmd in "Zz":
                    close()
                    loop, cur = [], start
                    continue
            rel, c = cmd.islower(), cmd.upper()
            ox, oy = cur if rel else (0.0, 0.0)
            if c == "M":
                close()
                cur = start = (ox + num(), oy + num())
                loop = [cur]
                cmd = "l" if rel else "L"  # further pairs after a moveto are linetos
            elif c == "L":
                cur = (ox + num(), oy + num())
                loop.append(cur)
            elif c == "H":
                cur = (ox + num(), cur[1])
                loop.append(cur)
            elif c == "V":
                cur = (cur[0], oy + num())
                loop.append(cur)
            elif c == "C":
                p1, p2, p3 = (ox + num(), oy + num()), (ox + num(), oy + num()), (ox + num(), oy + num())
                _cubic(cur, p1, p2, p3, tol, loop)
                cur = p3
            elif c == "Q":
                q, p3 = (ox + num(), oy + num()), (ox + num(), oy + num())
                p1 = (cur[0] + 2 / 3 * (q[0] - cur[0]), cur[1] + 2 / 3 * (q[1] - cur[1]))
                p2 = (p3[0] + 2 / 3 * (q[0] - p3[0]), p3[1] + 2 / 3 * (q[1] - p3[1]))
                _cubic(cur, p1, p2, p3, tol, loop)
                cur = p3
            else:
                raise ValueError(f"desteklenmeyen SVG path komutu: {cmd}")
        close()
    return loops, w, h


def outlines(mask: np.ndarray) -> tuple[list[list[Point]], float, float]:
    """Trace the mask once (same vtracer settings as the SVG); scale to any size with write_dxf."""
    return svg_outlines(to_svg(mask, mask.shape[1]))


def write_dxf(path: Path, traced: tuple[list[list[Point]], float, float], width_mm: float,
              circles: list[tuple[float, float, float]] = ()) -> None:
    """Closed LWPOLYLINEs (+ exact CIRCLEs, given as centre x, centre y, radius in mm) on layer KESIM."""
    loops, w, h = traced
    s = width_mm / w
    doc = ezdxf.new("R2010", setup=False)
    doc.units = units.MM
    doc.header["$MEASUREMENT"] = 1  # metric
    doc.layers.add(LAYER, color=7)
    msp = doc.modelspace()
    for loop in loops:
        msp.add_lwpolyline([(x * s, (h - y) * s) for x, y in loop], close=True, dxfattribs={"layer": LAYER})
    for cx, cy, r in circles:
        msp.add_circle((cx, cy), r, dxfattribs={"layer": LAYER})
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(path)
