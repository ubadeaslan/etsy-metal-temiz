"""Fix options for cut-check findings, and the edit steps / editor endpoints of the panel."""
import re

import numpy as np
import pytest
from fastapi.testclient import TestClient

from metal import cutcheck, hat, onarim, raster, store
from metal.web.app import app
from tests import ornek

PPM = 3.0  # px per mm in the synthetic masks below
client = TestClient(app, base_url="http://127.0.0.1:8765")


def _params(mask, **kw):
    return cutcheck.Params(width_mm=mask.shape[1] / PPM, **kw)


def _fix(mask, code, key=None):
    p = _params(mask)
    res = cutcheck.check(mask, p)
    item = next(it for it in res.items if it["code"] == code)
    fixes, auto, _ = onarim.fixes_for(onarim.Scene(mask, p), item)
    fix = fixes[key or auto]
    return fix, auto, fix.apply(mask), p


def _numeral_between_ticks():
    """A frame with two tick marks pointing at a floating block, like the 9 between its clock ticks."""
    m = np.zeros((300, 400), dtype=bool)
    m[:30], m[-30:], m[:, :30], m[:, -30:] = True, True, True, True
    m[143:158, 30:150] = True       # left tick, 5 mm thick, ends 5 mm before the numeral
    m[143:158, 250:370] = True      # right tick, ends 5 mm after it
    m[105:195, 165:235] = True      # the floating "numeral"
    return m


def test_floating_numeral_is_joined_by_both_ticks():
    m = _numeral_between_ticks()
    fix, auto, out, p = _fix(m, "ADA")
    assert auto == "uzat" and fix.note == "iki taraftan"
    assert "ADA" not in {f["code"] for f in cutcheck.check(out, p).findings}
    added = fix.add
    assert added[:, : added.shape[1] // 2].any() and added[:, added.shape[1] // 2:].any()  # both sides grew
    assert (out & ~m)[135:166].sum() == (out & ~m).sum()  # only along the ticks' own band


def test_bridge_shift_and_delete_options():
    m = np.zeros((300, 400), dtype=bool)
    m[200:, :] = True                # ground
    m[150:197, 150:250] = True       # block 1 mm above it: an unnoticeable move joins it
    fix, auto, out, p = _fix(m, "ADA")
    assert auto == "kaydir"
    assert cutcheck.check(out, p).ok
    for key in ("kopru", "sil"):
        fix, _, out, _ = _fix(m, "ADA", key)
        assert fix.ok and "ADA" not in {f["code"] for f in cutcheck.check(out, p).findings}
    m2 = m.copy()
    m2[150:197] = False
    m2[100:150, 150:250] = True      # 17 mm away: the bridge is picked, the part stays where it was drawn
    fix, auto, out, p = _fix(m2, "ADA")
    assert auto == "kopru" and cutcheck.check(out, p).ok
    assert (out & m2).sum() == m2.sum()


def test_warning_fixes_clear_their_warning():
    m = np.ones((300, 300), dtype=bool)
    m[100:200, 100:200] = False
    m[148:152, 100:160] = True       # 1.3 mm spike into the window
    for key in ("kalin", "sil"):
        _, _, out, p = _fix(m, "UC", key)
        assert "UC" not in {f["code"] for f in cutcheck.check(out, p).findings}, key

    m = np.ones((300, 300), dtype=bool)
    yy, xx = np.ogrid[:300, :300]
    m[(yy - 150) ** 2 + (xx - 150) ** 2 <= 4 ** 2] = False  # 2.7 mm hole
    for key in ("buyut", "kapat"):
        _, _, out, p = _fix(m, "DELIK", key)
        assert "DELIK" not in {f["code"] for f in cutcheck.check(out, p).findings}, key

    m = np.ones((300, 400), dtype=bool)
    m[148:152, 60:340] = False       # long 1.3 mm slit: opened, not filled
    fix, auto, out, p = _fix(m, "BOSLUK")
    assert auto == "ac"
    assert "BOSLUK" not in {f["code"] for f in cutcheck.check(out, p).findings}


def test_auto_fixes_everything_on_a_design():
    m = _numeral_between_ticks()
    m[60:64, 60:120] = False         # plus a narrow slit in the frame area
    m[40:70, 40:130] = True
    m[54:57, 50:120] = False
    p = _params(m)
    out, done = onarim.apply_auto(m, p, cutcheck.check(m, p))
    assert done >= 2 and cutcheck.check(out, p).ok


# --- panel ------------------------------------------------------------------------------------------

def _design_with_floating_moon() -> str:
    res = client.post("/yukle", data={"product_type": "duvar", "name": "Dağ"},
                      files={"file": ("x.png", ornek.mountain_scene(floating_moon=True), "image/png")}, follow_redirects=False)
    design_id = re.search(r"/t/([a-z0-9-]+)", res.headers["location"]).group(1)
    client.post(f"/t/{design_id}/kontrol", data={"width_in": 24, "min_width_mm": 3, "min_hole_mm": 4, "min_gap_mm": 2})
    return design_id


def test_fix_cards_apply_undo_and_revert():
    design_id = _design_with_floating_moon()
    rec = store.load(design_id)
    assert not rec["check"]["ok"]
    card = rec["check"]["fixes"]["groups"][0]["cards"][0]
    assert card["code"] == "ADA" and card["label"] == "P1"
    assert (store.design_dir(design_id) / card["tile"]).exists()
    page = client.get(f"/t/{design_id}")
    assert "Düzeltmeler" in page.text and "P1" in page.text

    res = client.post(f"/t/{design_id}/onarim", follow_redirects=False,
                      data={"code": "ADA", "y": card["ref"][0], "x": card["ref"][1], "option": "kopru"})
    assert "ok=" in res.headers["location"]
    rec = store.load(design_id)
    assert rec["check"]["ok"] and len(rec["edit"]["versions"]) == 1
    assert "P1 köprü" in rec["edit"]["versions"][0]["note"]

    # the same card again: the part is attached now, so the stale form gets a clear message
    res = client.post(f"/t/{design_id}/onarim", follow_redirects=False,
                      data={"code": "ADA", "y": card["ref"][0], "x": card["ref"][1], "option": "kopru"})
    assert "err=" in res.headers["location"]

    client.post(f"/t/{design_id}/onarim/geri")
    rec = store.load(design_id)
    assert not rec["check"]["ok"] and not rec.get("edit")

    client.post(f"/t/{design_id}/mockup", data={"card": ["boyut", "bilgi"]})  # images of the original
    client.post(f"/t/{design_id}/onarim/otomatik")
    rec = store.load(design_id)
    assert rec["check"]["ok"] and hat.mockups_stale(rec)  # the design changed under its images
    res = client.post(f"/t/{design_id}/kit", follow_redirects=False)
    assert "err=" in res.headers["location"]

    # one click makes the set again from the fixed design: same cards, the user's order kept
    rec = store.load(design_id)
    client.post(f"/t/{design_id}/mockup/sira", data={"file": rec["mockups"][-1]["file"], "direction": -1})
    kinds = [m["kind"] for m in store.load(design_id)["mockups"]]
    assert "Görselleri yenile" in client.get(f"/t/{design_id}").text
    res = client.post(f"/t/{design_id}/mockup/yenile", follow_redirects=False)
    assert "ok=" in res.headers["location"]
    rec = store.load(design_id)
    assert [m["kind"] for m in rec["mockups"]] == kinds and not hat.mockups_stale(rec)
    client.post(f"/t/{design_id}/onarim/orijinal")
    rec = store.load(design_id)
    assert not rec["check"]["ok"] and not rec.get("edit")
    assert hat.mockups_stale(rec)  # the images now show the fixed design, not the original
    assert not list((store.design_dir(design_id) / "duzenleme").iterdir())


def _bits(mask: np.ndarray) -> bytes:
    return np.packbits(mask.astype(np.uint8).ravel()).tobytes()


def test_editor_check_and_save():
    design_id = _design_with_floating_moon()
    assert client.get(f"/t/{design_id}/duzenle").status_code == 200
    png = client.get(f"/t/{design_id}/duzenle/maske.png")
    assert png.headers["content-type"] == "image/png"
    from io import BytesIO

    from PIL import Image
    mask = np.asarray(Image.open(BytesIO(png.content)).convert("L")) < 128
    h, w = mask.shape

    res = client.post(f"/t/{design_id}/duzenle/kontrol?w={w}&h={h}", content=_bits(mask))
    data = res.json()
    assert not data["ok"] and data["counts"]["ADA"] == 1 and data["layer"].startswith("data:image/png")

    # erase the floating moon by hand, as the eraser would
    rec = store.load(design_id)
    card = rec["check"]["fixes"]["groups"][0]["cards"][0]
    y0, x0, y1, x1 = card["bbox"]
    edited = mask.copy()
    edited[y0:y1, x0:x1] = False
    data = client.post(f"/t/{design_id}/duzenle/kontrol?w={w}&h={h}", content=_bits(edited)).json()
    assert data["ok"], data["findings"]

    res = client.post(f"/t/{design_id}/duzenle/kaydet?w={w}&h={h}", content=_bits(edited))
    assert res.json()["url"].startswith(f"/t/{design_id}?ok=")
    rec = store.load(design_id)
    assert rec["check"]["ok"] and rec["edit"]["versions"][-1]["note"] == "düzenleyici"

    bad = client.post(f"/t/{design_id}/duzenle/kontrol?w={w}&h={h}", content=b"\x00" * 10)
    assert bad.status_code == 400


def test_clock_edit_keeps_one_exact_hub_at_any_width():
    res = client.post("/yukle", data={"product_type": "saat", "name": "Saat"},
                      files={"file": ("x.png", ornek.clock_face(900), "image/png")}, follow_redirects=False)
    design_id = re.search(r"/t/([a-z0-9-]+)", res.headers["location"]).group(1)
    client.post(f"/t/{design_id}/kontrol", data={"width_in": 16, "min_width_mm": 3, "min_hole_mm": 4, "min_gap_mm": 2})
    mask = np.asarray(raster.load_mask(store.design_dir(design_id) / "secilen.png"))
    png = client.get(f"/t/{design_id}/duzenle/maske.png").content
    from io import BytesIO

    from PIL import Image
    base = np.asarray(Image.open(BytesIO(png)).convert("L")) < 128
    assert base.shape == mask.shape
    h, w = base.shape
    client.post(f"/t/{design_id}/duzenle/kaydet?w={w}&h={h}", content=_bits(base))
    for width_in in (16, 36):  # the 10 mm shaft hole is re-made at every width, never scaled with the edit
        client.post(f"/t/{design_id}/kontrol", data={"width_in": width_in, "min_width_mm": 3, "min_hole_mm": 4, "min_gap_mm": 2})
        m = raster.load_mask(store.design_dir(design_id) / "secilen.png")
        hole_px = (~m[h // 2 - 40:h // 2 + 40, w // 2 - 40:w // 2 + 40]).sum()
        expected = np.pi * (5 * m.shape[1] / (width_in * 25.4)) ** 2
        assert hole_px == pytest.approx(expected, rel=0.25), width_in
