"""One folder per design: calisma/tasarimlar/<id>/kayit.json is the production record."""
from __future__ import annotations

import json
import re
import secrets
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from . import config

RECORD = "kayit.json"

PRODUCT_TYPES = {
    "saat": "Saat",
    "duvar": "Duvar süsü",
    "tabela": "İsim / aile tabelası",
    "serbest": "Serbest",
    "portre": "Özel portre (fotoğraftan)",
}

STAGES = [
    ("aday", "Adaylar"),
    ("kontrol", "Kontrol"),
    ("mockup", "Mockup"),
    ("listing", "Listing"),
    ("kit", "Kit"),
]


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=config.ROOT,
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() or "uncommitted"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def slugify(text: str, limit: int = 32) -> str:
    table = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    slug = re.sub(r"[^a-z0-9]+", "-", text.translate(table).lower()).strip("-")
    return slug[:limit].strip("-") or "tasarim"


def design_dir(design_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9-]+", design_id):
        raise ValueError("geçersiz tasarım kimliği")
    return config.DESIGNS / design_id


def create(product_type: str, brief: str, name: str = "", source: str = "ai", sizes_in: list[float] | None = None) -> dict:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    design_id = f"{stamp}-{slugify(name or brief, 24)}-{secrets.token_hex(2)}"
    sku = next_sku()  # before the folder exists, so the new design does not count itself
    folder = design_dir(design_id)
    (folder / "adaylar").mkdir(parents=True)
    record = {
        "id": design_id,
        "sku": sku,
        "created": now(),
        "updated": now(),
        "sizes_in": sorted(sizes_in or config.load_settings()["sizes_in"]),
        "name": name.strip() or brief.strip()[:60] or "Yeni tasarım",
        "product_type": product_type if product_type in PRODUCT_TYPES else "serbest",
        "brief": brief.strip(),
        "source": source,
        "ai_used": source == "ai",
        "generator_commit": _git_commit(),
        "generations": [],
        "candidates": [],
        "chosen": None,
        "check": None,
        "multi_piece": {"allowed": False, "reason": ""},
        "vector": None,
        "mockups": [],
        "listing": None,
        "preflight": None,
        "kit": None,
        "licenses": [],
        "events": [],
    }
    event(record, f"oluşturuldu ({source})")
    save(record)
    return record


def load(design_id: str) -> dict:
    return json.loads((design_dir(design_id) / RECORD).read_text(encoding="utf-8"))


def save(record: dict) -> None:
    record["updated"] = now()
    path = design_dir(record["id"]) / RECORD
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def event(record: dict, text: str) -> None:
    record.setdefault("events", []).append({"at": now(), "text": text})


def list_all() -> list[dict]:
    if not config.DESIGNS.exists():
        return []
    records = []
    for folder in config.DESIGNS.iterdir():
        path = folder / RECORD
        if path.exists():
            try:
                records.append(json.loads(path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                continue
    return sorted(records, key=lambda r: r["created"], reverse=True)


def delete(design_id: str) -> None:
    """Remove the design folder for good; its SKU becomes free for the next new design."""
    folder = design_dir(design_id)
    if folder.exists():
        shutil.rmtree(folder)


# --- SKU ------------------------------------------------------------------------------------------

def normalize_sku(sku: str) -> str:
    return re.sub(r"\s+", "", str(sku or "")).upper()


def next_sku() -> str:
    """Lowest free number from the configured start (SKU-1001, SKU-1002, ...); freed numbers are reused."""
    settings = config.load_settings()
    prefix, number = settings["sku_prefix"], int(settings["sku_start"])
    used = {normalize_sku(r.get("sku")) for r in list_all()}
    while normalize_sku(f"{prefix}{number}") in used:
        number += 1
    return f"{prefix}{number}"


def order_sku(parent: str) -> str:
    """An order made from a listing design: the listing's SKU with -S1, -S2 ... (keeps the number pool free)."""
    used = {normalize_sku(r.get("sku")) for r in list_all()}
    k = 1
    while normalize_sku(f"{parent}-S{k}") in used:
        k += 1
    return normalize_sku(f"{parent}-S{k}")


def set_sku(record: dict, sku: str) -> dict:
    sku = normalize_sku(sku)
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{0,31}", sku):
        raise ValueError("SKU boş olamaz; harf, rakam, tire, nokta ve alt çizgi kullan (en çok 32 karakter).")
    other = next((r for r in list_all() if r["id"] != record["id"] and normalize_sku(r.get("sku")) == sku), None)
    if other:
        raise ValueError(f"{sku} zaten kullanılıyor: {other['name']}")
    if sku != record.get("sku"):
        event(record, f"SKU: {record.get('sku') or '-'} → {sku}")
        record["sku"] = sku
        save(record)
    return record


def backfill_skus() -> None:
    """Designs made before SKUs existed get the next free number, oldest first."""
    for record in sorted(list_all(), key=lambda r: r["created"]):
        if not record.get("sku"):
            record["sku"] = next_sku()
            event(record, f"SKU atandı: {record['sku']}")
            save(record)


def stage(record: dict) -> str:
    if record.get("kit"):
        return "kit"
    if record.get("listing"):
        return "listing"
    if record.get("mockups"):
        return "mockup"
    if record.get("check"):
        return "kontrol"
    return "aday"


def thumb(record: dict) -> str | None:
    """Best preview file (relative to the design folder)."""
    if record.get("mockups"):
        return record["mockups"][0]["file"]
    if record.get("chosen"):
        return "secilen.png" if (design_dir(record["id"]) / "secilen.png").exists() else record["chosen"]
    if record.get("candidates"):
        return record["candidates"][-1]
    return None


def add_license(record: dict, name: str) -> None:
    if name not in record.setdefault("licenses", []):
        record["licenses"].append(name)
