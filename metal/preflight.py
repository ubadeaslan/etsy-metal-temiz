"""Listing preflight: Etsy's limits on title, tags, description and images."""
from __future__ import annotations

import re

from PIL import Image

from . import store

HATA, UYARI = "HATA", "UYARI"

TITLE_MAX = 140
TITLE_ONCE_CHARS = "%:&+"
TITLE_WORDS_SOFT_MAX = 15
TAG_COUNT = 13
TAG_MAX = 20
TAG_CHARSET = re.compile(r"^(?:[^\W_]|[\s\-'™©®])+$")
MIN_IMAGES_SOFT = 5
MIN_IMAGE_PX = 2000

FORBIDDEN_CLAIMS = (
    "bestseller", "best seller", "best-seller", "best selling", "best-selling", "number one", "#1",
    "guaranteed", "guarantee", "top rated", "top-rated",
)


def _f(level: str, code: str, msg: str) -> dict:
    return {"level": level, "code": code, "msg": msg}


def check(record: dict) -> list[dict]:
    out: list[dict] = []
    listing = record.get("listing") or {}
    title = listing.get("title", "")
    tags = listing.get("tags", [])
    desc = listing.get("description", "")

    # --- title / tags / description -------------------------------------------------------------
    if not title:
        out.append(_f(HATA, "META-001", "başlık boş"))
    if len(title) > TITLE_MAX:
        out.append(_f(HATA, "META-001", f"başlık {len(title)} karakter (en çok {TITLE_MAX})"))
    for char in TITLE_ONCE_CHARS:
        if title.count(char) > 1:
            out.append(_f(HATA, "META-001", f"başlıkta '{char}' {title.count(char)} kez (Etsy en çok 1 izin verir)"))
    if len(title.split()) >= TITLE_WORDS_SOFT_MAX:
        out.append(_f(UYARI, "META-001", f"başlık {len(title.split())} kelime (önerilen < {TITLE_WORDS_SOFT_MAX})"))
    if len(tags) > TAG_COUNT:
        out.append(_f(HATA, "META-002", f"{len(tags)} tag (Etsy en çok {TAG_COUNT})"))
    elif len(tags) < TAG_COUNT:
        out.append(_f(UYARI, "META-002", f"{len(tags)} tag — 13'ün hepsini kullan"))
    seen = set()
    for tag in tags:
        if len(tag) > TAG_MAX:
            out.append(_f(HATA, "META-002", f"tag '{tag}' {len(tag)} karakter (en çok {TAG_MAX})"))
        if not TAG_CHARSET.match(tag):
            out.append(_f(HATA, "META-002", f"tag '{tag}' izin verilmeyen karakter içeriyor"))
        if tag in seen:
            out.append(_f(HATA, "META-002", f"tag tekrarı: '{tag}'"))
        seen.add(tag)
    single = sum(1 for t in tags if len(t.split()) == 1)
    if single > 2:
        out.append(_f(UYARI, "META-002", f"{single} tek kelimelik tag (çok kelimeli ifade daha verimli)"))
    if not desc:
        out.append(_f(HATA, "META-003", "açıklama boş"))
    elif len(desc) < 400:
        out.append(_f(UYARI, "META-003", f"açıklama kısa ({len(desc)} karakter) — ilk cümleler aramaya girer"))

    # --- claims ---------------------------------------------------------------------------------
    surfaces = {"başlık": title, "tag": " | ".join(tags), "açıklama": desc}
    for label, text in surfaces.items():
        low = text.lower()
        for claim in FORBIDDEN_CLAIMS:
            if re.search(r"(?<!\w)" + re.escape(claim) + r"(?!\w)", low):
                out.append(_f(HATA, "CLAIM-001", f"{label}: yasak iddia '{claim}'"))

    # --- product type: a clock is sold as a clock, nothing else is ------------------------------
    if title:
        says_clock = re.search(r"(?<!\w)clocks?(?!\w)", title.lower()) is not None
        if record.get("product_type") == "saat" and not says_clock:
            out.append(_f(UYARI, "TYPE-001", "ürün tipi Saat ama başlıkta 'clock' yok"))
        elif record.get("product_type") != "saat" and says_clock:
            out.append(_f(HATA, "TYPE-001", f"ürün tipi {store.PRODUCT_TYPES.get(record.get('product_type'), '?')} "
                                            "ama başlıkta 'clock' var — listing metnini yeniden yaz"))

    # --- check output (the kit needs its SVG and stats) and images ------------------------------
    if not record.get("check"):
        out.append(_f(HATA, "CUT-001", "kesilebilirlik kontrolü yapılmadı (kit SVG'yi ondan alır)"))
    mockups = record.get("mockups") or []
    if not mockups:
        out.append(_f(HATA, "IMG-001", "listing görseli yok"))
    else:
        if len(mockups) < MIN_IMAGES_SOFT:
            out.append(_f(UYARI, "IMG-001", f"{len(mockups)} görsel (önerilen en az {MIN_IMAGES_SOFT})"))
        first = store.design_dir(record["id"]) / mockups[0]["file"]
        if first.exists():
            with Image.open(first) as img:
                if min(img.size) < MIN_IMAGE_PX:
                    out.append(_f(HATA, "IMG-001", f"ilk görselin kısa kenarı {min(img.size)} px (en az {MIN_IMAGE_PX})"))
    return out


def has_errors(findings: list[dict]) -> bool:
    return any(f["level"] == HATA for f in findings)
