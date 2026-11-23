import io

import numpy as np
from PIL import Image, ImageDraw

from metal import compose, cutcheck, raster
from tests import ornek


def _mask(png: bytes) -> np.ndarray:
    return raster.prepare(png)


def codes(res, level=None):
    return {f["code"] for f in res.findings if level is None or f["level"] == level}


def test_floating_part_is_an_error():
    res = cutcheck.check(_mask(ornek.mountain_scene(floating_moon=True)), cutcheck.Params(width_mm=600))
    assert not res.ok
    assert "ADA" in codes(res, "HATA")


def test_multi_piece_turns_islands_into_warning():
    res = cutcheck.check(_mask(ornek.mountain_scene(floating_moon=True)), cutcheck.Params(width_mm=600, multi_piece=True))
    assert "ADA" in codes(res, "UYARI")
    assert res.ok


def test_hairline_bridge_holding_a_big_part_is_an_error():
    res = cutcheck.check(_mask(ornek.mountain_scene(floating_moon=False, thin_bridge=True)), cutcheck.Params(width_mm=600))
    assert "KOPRU" in codes(res, "HATA")


def test_clean_design_passes_and_reports_stats():
    res = cutcheck.check(_mask(ornek.mountain_scene(floating_moon=False)), cutcheck.Params(width_mm=600))
    assert res.ok, res.findings
    assert res.stats["weight_kg_steel"] > 0
    assert abs(res.stats["width_mm"] - 600) < 1


def test_crop_edge_does_not_fake_narrow_gaps():
    mask = np.ones((400, 600), dtype=bool)
    mask[100:300, 150:450] = False  # one big window
    res = cutcheck.check(mask, cutcheck.Params(width_mm=600))
    assert "BOSLUK" not in codes(res)


def test_clock_hub_has_hole_and_connects():
    mask = _mask(ornek.clock_face())
    with_hub = compose.add_clock_hub(mask, 508, 0.12, 10)
    h, w = with_hub.shape
    assert not with_hub[h // 2, w // 2]  # shaft hole
    assert with_hub[h // 2, w // 2 + int(w * 0.04)]  # solid hub around it
    assert cutcheck.check(with_hub, cutcheck.Params(width_mm=508)).ok


def test_small_hole_warning():
    mask = np.ones((600, 600), dtype=bool)
    yy, xx = np.ogrid[:600, :600]
    mask[(yy - 300) ** 2 + (xx - 300) ** 2 <= 4 ** 2] = False  # ~2 mm hole at 4 px/mm
    res = cutcheck.check(mask, cutcheck.Params(width_mm=150))
    assert "DELIK" in codes(res, "UYARI")


def test_small_holes_of_the_design_survive_speck_cleanup():
    """Flag stars (~1.5 mm²) are the design: the cleanup keeps them, the check reports them."""
    mask = np.ones((400, 600), dtype=bool)  # 150 mm wide: 4 px/mm
    yy, xx = np.ogrid[:400, :600]
    for cx in range(100, 500, 40):
        mask[(yy - 200) ** 2 + (xx - cx) ** 2 <= 2.8 ** 2] = False  # ~25 px = 1.5 mm² each
    mask[100, 300] = False  # a one-pixel pinhole is dirt
    mask[300, 300:302] = False
    clean = cutcheck.remove_specks_mm(mask, 4.0, speck_mm2=2.0)
    assert not clean[200, 100:500:40].any()  # all ten stars still holes
    assert clean[100, 300] and clean[300, 300]  # pinholes filled
    res = cutcheck.check(clean, cutcheck.Params(width_mm=150))
    assert next(f["count"] for f in res.findings if f["code"] == "DELIK") == 10


def test_metal_specks_still_removed():
    mask = np.zeros((400, 600), dtype=bool)
    mask[50:350, 50:300] = True
    mask[200:204, 450:454] = True  # 1 mm² of loose metal at 4 px/mm
    clean = cutcheck.remove_specks_mm(mask, 4.0, speck_mm2=2.0)
    assert not clean[200:204, 450:454].any()


def test_inverted_upload_is_detected():
    img = Image.new("L", (800, 600), 0)
    ImageDraw.Draw(img).ellipse((200, 100, 600, 500), fill=255)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    mask = raster.prepare(buf.getvalue())
    assert mask.mean() > 0.6  # the white disk became the metal
