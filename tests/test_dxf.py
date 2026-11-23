import ezdxf
import numpy as np
from ezdxf import bbox, units

from metal import compose, raster, vector


def _ring(n: int = 400) -> np.ndarray:
    """A disk with a round hole: one outer and one inner outline."""
    yy, xx = np.ogrid[:n, :n]
    d2 = (yy - (n - 1) / 2) ** 2 + (xx - (n - 1) / 2) ** 2
    return (d2 <= (n * 0.48) ** 2) & (d2 > (n * 0.2) ** 2)


def test_svg_outlines_handles_relative_commands_and_translate():
    svg = ('<svg viewBox="0 0 100 50"><path d="m10 10 h20 v10 l-20 0 z M50 5 C60 5 70 15 70 25 Q60 40 50 25 Z" '
           'transform="translate(5,1)"/></svg>')
    loops, w, h = vector.svg_outlines(svg)
    assert (w, h) == (100, 50) and len(loops) == 2
    assert loops[0] == [(15, 11), (35, 11), (35, 21), (15, 21)]
    assert loops[1][0] == (55, 6) and len(loops[1]) > 4  # curves flattened into many points


def test_dxf_is_mm_closed_and_true_width(tmp_path):
    path = tmp_path / "ring.dxf"
    vector.write_dxf(path, vector.outlines(raster.crop(_ring())), 500.0)  # masks are cropped to the metal
    doc = ezdxf.readfile(path)
    assert doc.units == units.MM
    polys = doc.modelspace().query("LWPOLYLINE")
    assert len(polys) == 2 and all(p.closed and p.dxf.layer == "KESIM" for p in polys)
    box = bbox.extents(doc.modelspace())
    assert abs(box.size.x - 500) < 3 and abs(box.extmin.x) < 3 and abs(box.extmin.y) < 3


def test_clock_hole_becomes_an_exact_circle(tmp_path):
    from metal import hat

    mask = compose.add_clock_hub(_ring(600), 300, 0.12, 10)  # solid hub with a 10 mm hole at 300 mm wide
    record = {"product_type": "saat"}
    traced = hat.trace_for_dxf(record, mask)
    assert len(traced[0]) == len(vector.outlines(mask)[0]) - 1  # the traced shaft hole is left out
    for width in (300.0, 900.0):  # the hole stays 10 mm at every size
        path = tmp_path / f"saat-{width:.0f}.dxf"
        hat.write_dxf(record, traced, width, path)
        (circle,) = ezdxf.readfile(path).modelspace().query("CIRCLE")
        assert circle.dxf.radius == 5 and abs(circle.dxf.center.x - width / 2) < 1e-6
