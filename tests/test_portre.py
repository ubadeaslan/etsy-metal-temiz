"""Custom portraits: drawn from a photo (AI mocked here), name plate by code, orders as their own designs."""
import re
from urllib.parse import unquote

import numpy as np
import pytest
from fastapi.testclient import TestClient

from metal import cutcheck, hat, providers, raster, store, yazi
from metal.web.app import app
from tests import ornek

client = TestClient(app, base_url="http://127.0.0.1:8765")


def _portrait_like() -> np.ndarray:
    """A head on shoulders standing on a base bar, like the portrait prompt asks for."""
    m = np.zeros((900, 900), dtype=bool)
    yy, xx = np.ogrid[:900, :900]
    m |= (yy - 330) ** 2 + (xx - 450) ** 2 <= 230 ** 2         # head
    m |= (yy - 900) ** 2 / 1.6 + (xx - 450) ** 2 <= 380 ** 2    # shoulders
    m[(yy - 300) ** 2 + (xx - 370) ** 2 <= 30 ** 2] = False     # eyes cut out
    m[(yy - 300) ** 2 + (xx - 530) ** 2 <= 30 ** 2] = False
    m[820:, 40:860] = True                                      # base bar
    return raster.crop(m)


@pytest.mark.parametrize("text", ["İsa ve Esma", "Custom Text", "Gülşen Öztürk", "BOB"])
def test_name_plate_is_one_piece_under_the_design(text):
    m = _portrait_like()
    p = cutcheck.Params(width_mm=30 * 25.4)
    out = yazi.add_plate(m, text, p)
    assert out.shape[1] == m.shape[1] and out.shape[0] > m.shape[0]
    assert (out[:m.shape[0]] == m).all()  # the design's own rows are untouched
    res = cutcheck.check(out, p)
    assert "ADA" not in {f["code"] for f in res.findings}  # letter counters are tied to the plate
    letters = ~out[m.shape[0]:]
    assert letters.any()  # the name is cut through the plate
    assert (yazi.add_plate(m, "  ", p) == m).all()


def _png(mask: np.ndarray) -> bytes:
    return raster.png_bytes(raster.to_image(mask))


@pytest.fixture
def fake_ai(monkeypatch):
    calls = []

    def generate_images(provider, prompt, n, aspect, model=None, design_id=None, image_png=None):
        calls.append({"provider": provider, "prompt": prompt, "aspect": aspect, "photo": image_png})
        return [_png(_portrait_like())] * n, {"provider": provider, "model": "fake", "cost_usd": 0.0}

    monkeypatch.setattr(providers, "generate_images", generate_images)
    return calls


def test_portrait_flow_name_change_and_orders(fake_ai):
    res = client.post("/portre", follow_redirects=False,
                      data={"text": "Custom Text", "aspect": "yatay", "n": 2, "name": "Çift portresi"},
                      files={"file": ("foto.jpg", ornek.clock_face(500), "image/png")})
    design_id = re.search(r"/t/([a-z0-9-]+)", res.headers["location"]).group(1)
    assert "ok=" in res.headers["location"]
    rec = store.load(design_id)
    assert rec["product_type"] == "portre" and rec["text"] == {"content": "Custom Text"}
    assert len(rec["candidates"]) == 2 and (store.design_dir(design_id) / rec["portre"]["photo"]).exists()
    call = fake_ai[0]
    assert call["provider"] == "gemini" and call["photo"] and call["aspect"] == "4:3"
    assert "FILLED stencil" in call["prompt"] and "base bar" in call["prompt"]

    client.post(f"/t/{design_id}/sec", data={"candidate": rec["candidates"][0]})
    client.post(f"/t/{design_id}/kontrol", data={"width_in": 24, "min_width_mm": 3, "min_hole_mm": 4, "min_gap_mm": 2})
    rec = store.load(design_id)
    master = raster.load_mask(store.design_dir(design_id) / "secilen.png")
    base = hat.editor_mask(rec)
    assert master.shape[0] > base.shape[0]  # the plate hangs under the design
    page = client.get(f"/t/{design_id}").text
    assert "İsim plakası" in page and "Custom Text" in page

    client.post(f"/t/{design_id}/yazi", data={"text": "  İsa   ve Esma "})
    rec = store.load(design_id)
    assert rec["text"]["content"] == "İsa ve Esma"
    renamed = raster.load_mask(store.design_dir(design_id) / "secilen.png")
    assert renamed.shape != master.shape or (renamed != master).any()  # the plate was drawn again

    # an order without a photo: the same portrait, the customer's name, its own SKU
    res = client.post(f"/t/{design_id}/siparis", data={"text": "Boncuk"}, follow_redirects=False)
    order_id = re.search(r"/t/([a-z0-9-]+)", res.headers["location"]).group(1)
    order = store.load(order_id)
    assert order["sku"] == f"{rec['sku']}-S1" and order["text"]["content"] == "Boncuk"
    assert order["chosen"] == rec["chosen"] and order["check"] and order["parent"]["id"] == design_id
    assert (store.design_dir(order_id) / order["chosen"]).exists()
    assert store.load(design_id)["text"]["content"] == "İsa ve Esma"  # the listing design keeps its name
    assert len(fake_ai) == 1  # no AI call for a name-only order

    # an order with the customer's photo: a new portrait is drawn
    res = client.post(f"/t/{design_id}/siparis", data={"text": "Max"}, follow_redirects=False,
                      files={"file": ("kedi.jpg", ornek.clock_face(400), "image/png")})
    second = store.load(re.search(r"/t/([a-z0-9-]+)", res.headers["location"]).group(1))
    assert second["sku"] == f"{rec['sku']}-S2" and len(second["candidates"]) == 3 and len(fake_ai) == 2
    assert [o["text"] for o in store.load(design_id)["orders"]] == ["Boncuk", "Max"]
    assert store.next_sku() == "SKU-1002"  # orders do not use up listing numbers


def test_portrait_needs_gemini_and_fixes_leave_the_plate_alone(fake_ai):
    res = client.post("/portre", follow_redirects=False, data={"text": "Luna", "n": 1},
                      files={"file": ("f.png", ornek.clock_face(300), "image/png")})
    design_id = re.search(r"/t/([a-z0-9-]+)", res.headers["location"]).group(1)
    res = client.post(f"/t/{design_id}/uret", data={"brief": "", "provider": "openai", "n": 1}, follow_redirects=False)
    assert "err=" in res.headers["location"] and "Gemini" in unquote(res.headers["location"])  # portraits: Gemini only

    # a portrait with a floating part: the fix applies to the design, the plate is drawn again by code
    rec = store.load(design_id)
    m = _portrait_like()
    m[60:110, 60:110] = True  # a loose square in the corner
    rel = "adaylar/elle.png"
    raster.to_image(m).save(store.design_dir(design_id) / rel)
    rec["candidates"].append(rel)
    store.save(rec)
    client.post(f"/t/{design_id}/sec", data={"candidate": rel})
    client.post(f"/t/{design_id}/kontrol", data={"width_in": 30, "min_width_mm": 3, "min_hole_mm": 4, "min_gap_mm": 2})
    rec = store.load(design_id)
    cards = [c for g in rec["check"]["fixes"]["groups"] for c in g["cards"]]
    base_h = hat.editor_mask(rec).shape[0]
    assert all(c["bbox"][0] < base_h for c in cards)  # no cards inside the name plate
    client.post(f"/t/{design_id}/onarim/otomatik", data={"code": "ADA"})
    rec = store.load(design_id)
    assert "ADA" not in {f["code"] for f in rec["check"]["findings"]}
    assert rec["text"]["content"] == "Luna" and len(rec["edit"]["versions"]) == 1
