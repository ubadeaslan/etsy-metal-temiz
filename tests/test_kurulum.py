"""A fresh install: starts empty, keeps each person's data apart, runs on this computer only, on any system."""
import re
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from metal import __main__ as starter
from metal import config, hat, listing, sizes, store
from metal.web import app as web
from tests import ornek

BASE = "http://127.0.0.1:8765"
client = TestClient(web.app, base_url=BASE)
ROOT = Path(__file__).resolve().parent.parent


def test_fresh_install_has_no_shop_in_it():
    s = config.load_settings()
    assert s["shop"] == {"name": "", "slogan": "", "story": ""} and s["style_example"] == ""
    facts = {k: v for k, v in s["facts"].items() if k not in ("thickness_mm", "personalization", "clock_hands_included")}
    assert not any(facts.values()), facts  # nothing is claimed about a product until its maker says so
    assert store.list_all() == [] and hat.ready_cards() == []
    text = listing.build_description({}, "duvar", s["facts"], [], [], ["black"], s["shop"], ai_used=False)
    assert "Material" not in text and "THANK YOU FOR VISITING OUR SHOP!" in text


def test_ready_cards_are_the_shops_own():
    design_id = re.search(r"/t/([a-z0-9-]+)", client.post(
        "/yukle", data={"product_type": "duvar", "name": "Dağ"}, follow_redirects=False,
        files={"file": ("x.png", ornek.mountain_scene(False), "image/png")}).headers["location"]).group(1)
    client.post(f"/t/{design_id}/kontrol", data={"width_in": 16, "min_width_mm": 3, "min_hole_mm": 4, "min_gap_mm": 2})
    page = client.get(f"/t/{design_id}").text
    assert 'value="kargo"' not in page  # no promise is offered that the shop did not upload
    client.post(f"/t/{design_id}/mockup", data={"card": ["renkler", "kargo", "gumruk"]})
    assert [m["kind"] for m in store.load(design_id)["mockups"]] == ["finishes"]

    res = client.post("/ayarlar/kart/kargo", files={"file": ("k.png", ornek.mountain_scene(size=600), "image/png")},
                      follow_redirects=False)
    assert "ok=" in res.headers["location"] and client.get("/kart/kargo").status_code == 200
    assert 'value="kargo"' in client.get(f"/t/{design_id}").text and "/kart/kargo" in client.get("/ayarlar").text
    client.post(f"/t/{design_id}/mockup", data={"card": ["renkler", "kargo"]})
    assert [m["kind"] for m in store.load(design_id)["mockups"]] == ["finishes", "shipping"]

    client.post("/ayarlar/kart/kargo/sil")
    assert hat.ready_cards() == [] and client.get("/kart/kargo").status_code == 404
    client.post(f"/t/{design_id}/mockup/yenile")  # the card is gone: the rest is made again
    assert [m["kind"] for m in store.load(design_id)["mockups"]] == ["finishes"]
    for bad in ("baska", "..%2fayarlar"):
        res = client.post(f"/ayarlar/kart/{bad}", files={"file": ("k.png", b"x", "image/png")}, follow_redirects=False)
        assert res.status_code == 404 or "err=" in res.headers["location"]


def test_settings_keep_the_shops_own_choices():
    client.post("/ayarlar", data={"sku_prefix": " ab c-", "sku_start": "50", "shop_story": "We cut with care.",
                                  "style_example": "My own listing\r\ntext"})
    s = config.load_settings()
    assert (s["sku_prefix"], s["sku_start"], s["shop"]["story"]) == ("ABC-", 50, "We cut with care.")
    assert store.next_sku() == "ABC-50"
    assert listing.system_prompt(s["style_example"]).endswith("My own listing\ntext")
    assert "Olive Branch" in listing.system_prompt("") and "Olive Branch" not in listing.system_prompt(s["style_example"])


def test_only_this_computers_own_pages_are_served():
    assert client.get("/").status_code == 200
    assert TestClient(web.app, base_url="http://localhost:8765").get("/").status_code == 200
    assert TestClient(web.app, base_url="http://kotu-site.com").get("/").status_code == 403  # DNS rebinding
    for origin in ("https://kotu-site.com", "null", "http://127.0.0.1:9999"):
        assert client.post("/ayarlar", data={}, headers={"Origin": origin}).status_code == 403, origin
    assert client.post("/ayarlar", data={}, headers={"Origin": BASE}, follow_redirects=False).status_code == 303


@pytest.mark.parametrize("platform, command", [("darwin", "open"), ("linux", "xdg-open")])
def test_folders_open_without_windows(monkeypatch, tmp_path, platform, command):
    calls = []
    monkeypatch.delattr(web.os, "startfile", raising=False)
    monkeypatch.setattr(web.sys, "platform", platform)
    monkeypatch.setattr(web.subprocess, "run", lambda args, **kw: calls.append(args))
    web.show_folder(tmp_path)
    assert calls == [[command, str(tmp_path)]]


def test_tesseract_hint_fits_the_system(monkeypatch):
    monkeypatch.setattr(sizes.sys, "platform", "darwin")
    assert "brew install tesseract" in sizes.install_hint()


def test_two_copies_on_one_computer_do_not_share_a_panel(monkeypatch):
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        assert not starter.is_free(port)
        monkeypatch.setattr(starter, "PORTS", [port])
        monkeypatch.setattr(starter, "install_on", lambda p: "mine")
        assert starter.pick_port("mine") == (port, True)  # this copy: just open the browser
        assert starter.pick_port("another") == (None, False)  # another copy's panel is never shown as this one's
    assert client.get("/api/panel").json() == {"app": "etsy-metal", "install": web.INSTALL_ID}


def _tracked() -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git yok")
    files = [f for f in out.stdout.decode("utf-8").split("\0") if f]
    if out.returncode or not files:
        pytest.skip("git deposu değil (ZIP olarak indirilmiş)")
    return files


def test_no_key_and_no_personal_data_in_git():
    files = _tracked()
    assert not [f for f in files if f.startswith("calisma/") or (Path(f).name.startswith(".env") and f != ".env.example")]
    key = re.compile(rb"sk-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{30,}|AQ\.[0-9A-Za-z_-]{30,}|gh[pousr]_[A-Za-z0-9]{30,}")
    leaks = [f for f in files if (ROOT / f).is_file() and key.search((ROOT / f).read_bytes())]
    assert not leaks, leaks
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert re.findall(r"(?m)^\w+=(.*)$", example) == ["", ""]


def test_mac_starter_is_runnable():
    raw = (ROOT / "baslat.command").read_bytes()
    assert raw.startswith(b"#!/bin/bash\n") and b"\r" not in raw
    if sys.platform != "win32":
        assert (ROOT / "baslat.command").stat().st_mode & 0o111
