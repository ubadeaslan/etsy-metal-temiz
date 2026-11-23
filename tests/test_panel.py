"""End-to-end through the HTTP panel without any AI key: upload -> check -> mockups -> listing -> kit."""
import re

from fastapi.testclient import TestClient

from metal import config, store
from metal.listing import AI_DISCLOSURE
from metal.web.app import app
from tests import ornek

client = TestClient(app, base_url="http://127.0.0.1:8765")

TAGS = ["metal wall clock", "abstract clock", "modern wall clock", "minimalist clock", "large wall clock",
        "living room clock", "black wall clock", "gold wall clock", "unique wall clock", "metal clock",
        "housewarming gift", "office wall clock", "laser cut clock"]


def _set_facts():
    s = config.load_settings()
    s["facts"].update({"mounting": "Pre-drilled holes for wall mounting"})
    s["sizes_in"] = [16, 24]
    config.save_settings(s)


def _upload(product_type: str, name: str, png: bytes) -> str:
    res = client.post("/yukle", data={"product_type": product_type, "name": name},
                      files={"file": ("x.png", png, "image/png")}, follow_redirects=False)
    return re.search(r"/t/([a-z0-9-]+)", res.headers["location"]).group(1)


def _check(design_id: str) -> None:
    client.post(f"/t/{design_id}/kontrol", data={"width_in": 16, "min_width_mm": 3, "min_hole_mm": 4, "min_gap_mm": 2})


def test_pages_render_without_keys():
    for path in ("/", "/yeni", "/odalar", "/ayarlar"):
        res = client.get(path)
        assert res.status_code == 200, path
        assert "AI anahtarı henüz yok" in res.text


def test_full_line_without_ai():
    from PIL import Image

    from metal import hat, mockup

    _set_facts()
    for card in hat.READY:
        client.post(f"/ayarlar/kart/{card}", files={"file": ("k.png", ornek.clock_face(300), "image/png")})
    design_id = _upload("saat", "Saat", ornek.clock_face(900))
    _check(design_id)
    rec = store.load(design_id)
    assert rec["check"]["ok"], rec["check"]["findings"]

    client.post(f"/t/{design_id}/mockup", data={"card": ["gumruk", "bilgi", "montaj", "renkler", "kargo", "boyut"]})
    rec = store.load(design_id)
    assert rec["sku"] == "SKU-1001" and rec["sizes_in"] == [16, 24]
    assert [m["kind"] for m in rec["mockups"]] == ["finishes", "sizes", "info", "install", "shipping", "customs"]  # fixed order
    assert {"Playfair Display", "Inter", "Cormorant Garamond", "Montserrat", hat.READY_LICENSE} <= set(rec["licenses"])
    for item in rec["mockups"][-3:]:  # the shop's own ready-made images, at the listing size
        with Image.open(store.design_dir(design_id) / item["file"]) as img:
            assert img.size == mockup.CANVAS

    desc = ("Modern metal wall clock with flowing abstract lines. " * 10).strip()
    client.post(f"/t/{design_id}/listing/kaydet", data={
        "title": "Abstract Metal Wall Clock | Modern Minimalist Clock", "tags": ", ".join(TAGS), "description": desc,
    })
    rec = store.load(design_id)
    assert not [f for f in rec["preflight"] if f["level"] == "HATA"], rec["preflight"]

    res = client.post(f"/t/{design_id}/kit", follow_redirects=False)
    assert "ok=" in res.headers["location"], res.headers["location"]
    kit = store.design_dir(design_id) / "kit"
    assert (kit / "listing.txt").exists() and (kit / "atolye" / "tasarim.svg").exists()
    assert len(list((kit / "gorseller").iterdir())) == len(store.load(design_id)["mockups"])
    assert (kit / "listing.txt").read_text(encoding="utf-8").startswith("SKU\nSKU-1001\n")
    dxfs = sorted(p.name for p in (kit / "atolye" / "dxf").iterdir())
    assert dxfs == ["SKU-1001_16in_406mm.dxf", "SKU-1001_24in_610mm.dxf"]  # one per sale size, real mm
    assert (store.design_dir(design_id) / "tasarim.dxf").exists()
    assert 'width="406.40mm"' in (kit / "atolye" / "tasarim.svg").read_text(encoding="utf-8")
    assert AI_DISCLOSURE not in (kit / "listing.txt").read_text(encoding="utf-8")  # upload = no AI

    page = client.get(f"/t/{design_id}")
    assert page.status_code == 200 and "Kopyala" in page.text


def test_kit_ships_even_when_cut_check_fails():
    _set_facts()
    design_id = _upload("duvar", "Dağ", ornek.mountain_scene(floating_moon=True))
    _check(design_id)
    assert not store.load(design_id)["check"]["ok"]
    client.post(f"/t/{design_id}/mockup", data={"card": ["boyut"]})
    client.post(f"/t/{design_id}/listing/kaydet", data={
        "title": "Mountain Metal Wall Art | Cabin Decor", "tags": ", ".join(TAGS),
        "description": ("Mountain metal wall art for the cabin wall. " * 12).strip(),
    })
    res = client.post(f"/t/{design_id}/kit", follow_redirects=False)
    assert "ok=" in res.headers["location"], res.headers["location"]


def test_room_multi_upload_and_room_mockup():
    from io import BytesIO

    from PIL import Image

    from metal import rooms

    def jpg(color):
        buf = BytesIO()
        Image.new("RGB", (1536, 1024), color).save(buf, "JPEG")
        return buf.getvalue()

    res = client.post("/odalar/yukle", follow_redirects=False,
                      files=[("files", ("a.jpg", jpg((230, 225, 215)), "image/jpeg")),
                             ("files", ("b.jpg", jpg((60, 62, 66)), "image/jpeg"))])
    assert "ok=" in res.headers["location"]
    listed = rooms.list_rooms()
    assert len(listed) == 2

    a, b = listed[0]["id"], listed[1]["id"]
    design_id = _upload("duvar", "Dağ", ornek.mountain_scene(floating_moon=False))
    _check(design_id)
    # black gets three picks (only two kept), gold two, silver an unknown room (dropped), white one
    client.post(f"/t/{design_id}/mockup", data={
        "oda_black": f"{a},{b},{a}", "oda_gold": f"{b},{a}", "oda_silver": "yok-boyle-oda", "oda_white": b,
    })
    rec = store.load(design_id)
    assert [(m["finish"], m["room"]) for m in rec["mockups"]] == [
        ("black", a), ("black", b), ("gold", b), ("gold", a), ("white", b)]
    assert rec["oda_plani"] == {"black": [a, b], "gold": [b, a], "silver": [], "bronze": [], "white": [b]}
    gold_a = next(m["file"] for m in rec["mockups"] if m["finish"] == "gold" and m["room"] == a)
    client.post(f"/t/{design_id}/mockup/sil", data={"file": gold_a})
    assert store.load(design_id)["oda_plani"]["gold"] == [b]  # the gold mark leaves room a too

    # refresh keeps the set as it stands: colour-room pairs and the order the user gave
    last = store.load(design_id)["mockups"][-1]["file"]
    client.post(f"/t/{design_id}/mockup/sira", data={"file": last, "direction": -3})
    pairs = [(m["finish"], m["room"]) for m in store.load(design_id)["mockups"]]
    assert pairs[0] == ("white", b)
    client.post(f"/t/{design_id}/mockup/yenile")
    assert [(m["finish"], m["room"]) for m in store.load(design_id)["mockups"]] == pairs
    with Image.open(store.design_dir(design_id) / rec["mockups"][0]["file"]) as img:
        assert img.size == (3000, 3000)
    assert client.get(f"/t/{design_id}").status_code == 200


def test_generation_without_key_shows_error_not_crash():
    res = client.post("/yeni", data={"product_type": "saat", "brief": "abstract clock", "provider": "gemini", "n": 1},
                      follow_redirects=False)
    assert res.status_code == 303 and "err=" in res.headers["location"]


def test_sizes_are_chosen_per_design():
    res = client.post("/yukle", data={"product_type": "saat", "name": "Boy", "sizes_in": ["14", "12", "", "38", "29.92"]},
                      files={"file": ("x.png", ornek.clock_face(600), "image/png")}, follow_redirects=False)
    design_id = re.search(r"/t/([a-z0-9-]+)", res.headers["location"]).group(1)
    assert store.load(design_id)["sizes_in"] == [12, 14, 29.92, 38]  # 29.92 = typed as 76 cm
    res = client.post(f"/t/{design_id}/boylar", data={"sizes_in": ["20", "24"]}, follow_redirects=False)
    assert res.headers["location"].endswith("#boylar")  # back to the sizes box, not the top of the page
    assert store.load(design_id)["sizes_in"] == [20, 24]
    page = client.get(f"/t/{design_id}")
    assert "kayıtlı: 2 boy" in page.text and "<b>20&#34;, 24&#34;</b>" in page.text  # inch mark HTML-escaped
    # the sizes box is always open: the table and its save button are not hidden in a collapsed box
    box = page.text[page.text.index('id="boylar"'):]
    assert box.index("Boyları kaydet") < box.index("</section>") and "<details class=\"sizes" not in page.text


def test_sku_numbering_edit_and_delete():
    first = _upload("saat", "Bir", ornek.clock_face(400))
    second = _upload("saat", "Iki", ornek.clock_face(400))
    assert store.load(first)["sku"] == "SKU-1001" and store.load(second)["sku"] == "SKU-1002"

    res = client.post(f"/t/{second}/sku", data={"sku": "sku-1001"}, follow_redirects=False)
    assert "err=" in res.headers["location"]  # taken by the first design
    client.post(f"/t/{second}/sku", data={"sku": " sku-2000 "})
    assert store.load(second)["sku"] == "SKU-2000"

    res = client.post(f"/t/{first}/sil", follow_redirects=False)
    assert res.headers["location"].startswith("/?ok=") and not store.design_dir(first).exists()
    third = _upload("saat", "Uc", ornek.clock_face(400))
    assert store.load(third)["sku"] == "SKU-1001"  # the freed number is reused


def test_old_designs_get_skus_oldest_first():
    import json

    ids = [_upload("saat", n, ornek.clock_face(400)) for n in ("Eski", "Yeni")]
    for i, design_id in enumerate(ids):  # pretend they predate SKUs
        path = store.design_dir(design_id) / store.RECORD
        rec = json.loads(path.read_text(encoding="utf-8"))
        rec.pop("sku")
        rec["created"] = f"2026-11-1{4 + i}T10:00:00"
        path.write_text(json.dumps(rec), encoding="utf-8")
    client.get("/")
    assert [store.load(d)["sku"] for d in ids] == ["SKU-1001", "SKU-1002"]


def test_size_import_api(monkeypatch):
    from metal import sizes

    text = "\n".join(['Select an option', '30"x13"/76x34cm (US$132.00)', "76 cm", '41"x137105x47cm'])
    rows = client.post("/api/boylar/ayikla", data={"text": text}).json()["rows"]
    assert [r["w_in"] for r in rows] == [29.92, 30.0, 41.0] and rows[2]["note"]
    monkeypatch.setattr(sizes, "tesseract", lambda: None)
    res = client.post("/api/boylar/oku", files={"file": ("a.png", ornek.clock_face(200), "image/png")})
    assert res.status_code == 400 and "Tesseract" in res.json()["error"]


def test_size_screenshot_ocr():
    """A drawn Etsy-style size dropdown read back by Tesseract (skipped where it is not installed)."""
    from io import BytesIO

    import pytest
    from PIL import Image, ImageDraw

    from metal import mockup, sizes

    if not sizes.tesseract():
        pytest.skip("Tesseract kurulu değil")
    lines = ['30"x13"/76x34cm (US$132.00)', '35"x16"/90x40cm (US$176.00)', '41"x18"/105x47cm (US$209.00)',
             '79" x 35" / 200x89cm (US$880.00)']
    img = Image.new("RGB", (390, 30 + 26 * len(lines)), "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((8, 12 + 26 * i), line, font=mockup.font("Inter.ttf", 15), fill=(30, 30, 30))
    buf = BytesIO()
    img.save(buf, "PNG")
    res = client.post("/api/boylar/oku", files={"file": ("s.png", buf.getvalue(), "image/png")})
    assert [r["w_in"] for r in res.json()["rows"]] == [30, 35, 41, 79], res.json()


def test_delete_one_listing_image():
    design_id = _upload("saat", "Saat", ornek.clock_face(600))
    _check(design_id)
    client.post(f"/t/{design_id}/mockup", data={"card": ["renkler", "boyut", "detay"]})
    first, second, third = (m["file"] for m in store.load(design_id)["mockups"])
    res = client.post(f"/t/{design_id}/mockup/sil", data={"file": second}, follow_redirects=False)
    assert res.headers["location"] == f"/t/{design_id}"  # back to the same page, no banner, no jump
    rec = store.load(design_id)
    assert [m["file"] for m in rec["mockups"]] == [first, third]  # the rest keep their order
    assert not (store.design_dir(design_id) / second).exists()
    res = client.post(f"/t/{design_id}/mockup/sil", data={"file": second}, follow_redirects=False)
    assert "err=" in res.headers["location"]  # already gone
    assert "/mockup/sil" in client.get(f"/t/{design_id}").text


def test_product_type_is_picked_and_can_change():
    from metal import hat, raster

    before = len(store.list_all())
    res = client.post("/yukle", data={"name": "Tipsiz"}, files={"file": ("x.png", ornek.clock_face(600), "image/png")},
                      follow_redirects=False)
    assert res.headers["location"].startswith("/yeni?err="), res.headers["location"]  # no type, no design
    assert len(store.list_all()) == before

    design_id = _upload("saat", "Balık", ornek.clock_face(600))
    _check(design_id)
    master = lambda: raster.load_mask(store.design_dir(design_id) / hat.MASTER)  # noqa: E731
    clock_mask = master()
    client.post(f"/t/{design_id}/mockup", data={"card": ["detay"]})
    client.post(f"/t/{design_id}/listing/kaydet", data={
        "title": "Metal Wall Clock | Fish", "tags": ", ".join(TAGS), "description": "x" * 500})
    assert not hat.mockups_stale(store.load(design_id))

    res = client.post(f"/t/{design_id}/tip", data={"product_type": "duvar"}, follow_redirects=False)
    assert "ok=" in res.headers["location"]
    rec = store.load(design_id)
    assert rec["product_type"] == "duvar" and rec["kit"] is None
    assert hat.mockups_stale(rec)  # the photos still have the hands
    assert ("HATA", "TYPE-001") in {(f["level"], f["code"]) for f in rec["preflight"]}
    assert (master() != clock_mask).any()  # hub and shaft hole gone from the cut

    client.post(f"/t/{design_id}/mockup/yenile")
    assert not hat.mockups_stale(store.load(design_id))
    client.post(f"/t/{design_id}/tip", data={"product_type": "saat"})
    assert (master() == clock_mask).all()  # back as it was
    res = client.post(f"/t/{design_id}/tip", data={"product_type": "portre"}, follow_redirects=False)
    assert "err=" in res.headers["location"]
    assert 'action="/t/' + design_id + '/tip"' in client.get(f"/t/{design_id}").text
