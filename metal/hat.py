"""The line: each panel action is one function here. The web layer only does HTTP."""
from __future__ import annotations

import copy
import io
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from . import compose, config, cutcheck, listing, mockup, onarim, preflight, prompts, providers, raster, rooms, store, vector, yazi
from .sizes import dims, fmt_in

MASTER = "secilen.png"      # cleaned, cropped metal mask at working resolution
OVERLAY = "kontrol.png"
SVG = "tasarim.svg"
DXF = "tasarim.dxf"         # at the checked width; the kit adds one DXF per sale size
EDITS = "duzenleme"         # the user's fixed/edited cut masks (no clock hub), one file per step
FIXES = "onarim"            # preview tiles of the fix options, rewritten by every check
PHOTO = "foto.png"          # custom portrait: the customer's photo the candidates are drawn from


def trace_for_dxf(record: dict, mask: np.ndarray) -> tuple:
    """Outlines for DXF. A clock's shaft hole is left out here and added back as an exact circle."""
    return vector.outlines(compose.fill_center_hole(mask) if record["product_type"] == "saat" else mask)


def write_dxf(record: dict, traced: tuple, width_mm: float, path: Path) -> None:
    """One DXF at a real width in mm. Clocks get the shaft hole as a CIRCLE of the set diameter at the
    centre, so it stays exact at every size (a scaled SVG would scale the hole too)."""
    circles = []
    if record["product_type"] == "saat":
        _, w, h = traced
        hole_mm = config.load_settings()["cut"]["clock_hole_mm"]
        circles = [(width_mm / 2, h * width_mm / w / 2, hole_mm / 2)]
    vector.write_dxf(path, traced, width_mm, circles)


class LineError(RuntimeError):
    """User-facing stop (Turkish message)."""


# --- 1. candidates --------------------------------------------------------------------------------

def generate(record: dict, provider: str, n: int, brief: str | None = None, model: str | None = None,
             sample_text: str = "") -> dict:
    brief = (brief if brief is not None else record["brief"]).strip()
    image_png = None
    if record["product_type"] == "portre":  # drawn from the customer's photo; the brief is an optional note
        photo = store.design_dir(record["id"]) / (record.get("portre") or {}).get("photo", PHOTO)
        if not photo.is_file():
            raise LineError("Portre için fotoğraf yok — önce fotoğrafı yükle.")
        if provider != "gemini":
            raise LineError("Fotoğraftan portre şimdilik Gemini ile çiziliyor — sağlayıcı olarak Gemini'yi seç.")
        prompt = prompts.portrait_prompt(brief)
        aspect = prompts.PORTRAIT_ASPECTS.get(record["portre"].get("aspect", "dikey"), "4:5")
        image_png = photo.read_bytes()
    else:
        if not brief:
            raise LineError("Tarif boş — ne tasarlanacağını yaz.")
        prompt = prompts.build_prompt(record["product_type"], brief, sample_text)
        aspect = prompts.ASPECTS.get(record["product_type"], "1:1")
    images, info = providers.generate_images(provider, prompt, n, aspect, model=model, design_id=record["id"],
                                             image_png=image_png)
    folder = store.design_dir(record["id"])
    stamp = datetime.now().strftime("%H%M%S")
    files = []
    for i, data in enumerate(images, start=1):
        rel = f"adaylar/{stamp}-{info['provider']}-{i}.png"
        Image.open(io.BytesIO(data)).save(folder / rel, "PNG")
        files.append(rel)
    record["candidates"].extend(files)
    record["generations"].append({"at": store.now(), "brief": brief, "prompt": prompt, "aspect": aspect,
                                  "files": files, **info})
    record["brief"] = brief
    record["ai_used"] = True
    store.event(record, f"{len(files)} aday üretildi ({info['provider']} · {info['model']} · ~${info['cost_usd']:.2f})")
    store.save(record)
    return record


# --- custom portraits: photo in, filled stencil out, name plate drawn by code ------------------------

def clean_text(text: str) -> str:
    return " ".join(str(text or "").split())[:60]


def set_photo(record: dict, data: bytes, filename: str = "") -> None:
    """The photo a portrait is drawn from: turned upright, phone-screenshot bars cut off, long edge 1536."""
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    except Exception as exc:  # PIL raises many types for bad files
        raise LineError(f"Fotoğraf açılamadı ({filename}): {exc}") from exc
    rows = np.flatnonzero(np.asarray(img).mean(axis=(1, 2)) > 12)
    if rows.size:
        img = img.crop((0, int(rows[0]), img.width, int(rows[-1]) + 1))
    img.thumbnail((1536, 1536), Image.LANCZOS)
    img.save(store.design_dir(record["id"]) / PHOTO, "PNG")
    record.setdefault("portre", {})["photo"] = PHOTO
    store.event(record, f"portre fotoğrafı: {filename or PHOTO}")


def start_portrait(record: dict, photo: bytes, filename: str, text: str, aspect: str) -> dict:
    set_photo(record, photo, filename)
    record["portre"]["aspect"] = aspect if aspect in prompts.PORTRAIT_ASPECTS else "dikey"
    record["text"] = {"content": clean_text(text) or yazi.DEFAULT_TEXT}
    store.save(record)
    return record


def plate_text(record: dict) -> str:
    return clean_text((record.get("text") or {}).get("content", ""))


def with_text(record: dict, mask: np.ndarray, params: cutcheck.Params) -> np.ndarray:
    """Custom portraits get their name plate under the design (see yazi.py); the rest pass through."""
    text = plate_text(record)
    return yazi.add_plate(mask, text, params) if text else mask


def set_text(record: dict, text: str) -> str:
    text = clean_text(text)
    if not text:
        raise LineError("İsim boş olamaz — plakaya ne yazılacağını gir.")
    old = plate_text(record)
    record["text"] = {"content": text}
    record["kit"] = None
    store.event(record, f"isim plakası: {old or '-'} → {text}")
    store.save(record)
    if record.get("check"):
        recheck(record)
    return f"İsim plakası: {text}" + (" — kontrol yenilendi, görselleri de yenile." if record.get("mockups") else "")


def open_order(record: dict, text: str, photo: bytes | None = None, filename: str = "",
               provider: str = "gemini", n: int = 3) -> dict:
    """An order of a custom portrait as its own design: the listing design stays as it is. With a photo,
    a new portrait is drawn from it (AI); without, the same portrait (with its fixes) gets the new name."""
    text = clean_text(text)
    if not text:
        raise LineError("Siparişteki ismi yaz.")
    if record["product_type"] != "portre":
        raise LineError("Sipariş kopyası özel portreler için.")
    order = store.create("portre", record.get("brief", ""), name=f"{record['name']} · {text}",
                         source=record.get("source", "ai"), sizes_in=sizes(record))
    order["sku"] = store.order_sku(record.get("sku") or "PORTRE")
    order["parent"] = {"id": record["id"], "sku": record.get("sku")}
    order["text"] = {"content": text}
    order["portre"] = dict(record.get("portre") or {})
    src, dst = store.design_dir(record["id"]), store.design_dir(order["id"])
    record.setdefault("orders", []).append({"id": order["id"], "sku": order["sku"], "text": text,
                                            "at": store.now(), "new_photo": bool(photo)})
    store.event(record, f"sipariş açıldı: {order['sku']} ({text})")
    store.save(record)
    if photo:
        set_photo(order, photo, filename)
        store.save(order)
        try:
            generate(order, provider, n)
        except (providers.ProviderError, providers.BudgetError, LineError) as exc:
            raise LineError(f"Sipariş {order['sku']} açıldı ama portre çizilemedi: {exc} — sipariş sayfasından "
                            "\"Üret\" ile tekrar dene.") from exc
        return order
    edit = edit_info(record)
    files = [*record.get("candidates", []), *(v["file"] for v in (edit or {}).get("versions", [])),
             order["portre"].get("photo", "")]
    for rel in files:
        if rel and (src / rel).is_file():
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src / rel, dst / rel)
    order.update({
        "candidates": list(record.get("candidates", [])), "chosen": record.get("chosen"),
        "generations": copy.deepcopy(record.get("generations", [])), "ai_used": record.get("ai_used", False),
        "edit": copy.deepcopy(edit) if edit else None,
    })
    store.save(order)
    if record.get("check"):
        order["check"] = copy.deepcopy(record["check"])
        order["multi_piece"] = copy.deepcopy(record.get("multi_piece"))
        recheck(order)
    return order


def upload(record: dict, data: bytes, filename: str) -> dict:
    folder = store.design_dir(record["id"])
    rel = f"adaylar/yukleme-{datetime.now():%H%M%S}.png"
    try:
        raster.open_image(data).save(folder / rel, "PNG")
    except Exception as exc:  # PIL raises many types for bad files
        raise LineError(f"Görsel açılamadı ({filename}): {exc}") from exc
    record["candidates"].append(rel)
    record["chosen"] = rel
    store.event(record, f"kendi tasarımı yüklendi: {filename}")
    store.save(record)
    return record


def choose(record: dict, candidate: str) -> dict:
    if candidate not in record["candidates"]:
        raise LineError("Böyle bir aday yok.")
    record["chosen"] = candidate
    record["check"] = None  # a new choice invalidates downstream work (edits belong to the old candidate)
    record["mockups"] = []
    record["kit"] = None
    store.event(record, f"aday seçildi: {candidate}")
    store.save(record)
    return record


# --- sizes ----------------------------------------------------------------------------------------

def sizes(record: dict) -> list[float]:
    """The design's sale sizes (inches wide). Records from before per-design sizes use the Ayarlar default."""
    return sorted(record.get("sizes_in") or config.load_settings()["sizes_in"])


def aspect(record: dict) -> float | None:
    """Height / width of the checked design (None before the cut check)."""
    stats = (record.get("check") or {}).get("stats") or {}
    return stats["height_mm"] / stats["width_mm"] if stats.get("width_mm") else None


def size_dims(record: dict) -> list[dict]:
    """Every sale size with its real height, labelled in inches and cm (see sizes.dims)."""
    ratio = aspect(record)
    return [dims(w, ratio) for w in sizes(record)]


def set_product_type(record: dict, product_type: str) -> str:
    """Change what the piece is (e.g. a design uploaded as Saat that is wall decor). Only a clock gets the
    hub, the shaft hole and hands on the photos, so the check runs again, the photos are marked as made
    from another version, and the listing text has to be written again (preflight flags 'clock' in it)."""
    old = record["product_type"]
    if old == "portre" or product_type == "portre":
        raise LineError("Özel portrenin tipi değiştirilmez.")
    if product_type not in store.PRODUCT_TYPES:
        raise LineError("Ürün tipini seç.")
    label = store.PRODUCT_TYPES[product_type]
    if product_type == old:
        return f"Ürün tipi zaten {label}."
    record["product_type"] = product_type
    record["kit"] = None
    if record.get("mockups"):
        record["mockups_from"] = None  # drawn as the old type (hands or none): stale until made again
    store.event(record, f"ürün tipi: {store.PRODUCT_TYPES[old]} → {label}")
    store.save(record)
    notes = [f"Ürün tipi: {label}."]
    if record.get("check"):
        recheck(record)
        if "saat" in (old, product_type):
            notes.append("Kontrol yenilendi: göbek ve mekanizma deliği " +
                         ("eklendi." if product_type == "saat" else "kaldırıldı."))
    elif record.get("listing"):
        refresh_preflight(record)
    if record.get("mockups"):
        notes.append("Görselleri yenile.")
    if record.get("listing"):
        notes.append("Listing metnini yeniden yaz.")
    return " ".join(notes)


def set_sizes(record: dict, sizes_in: list[float]) -> dict:
    if not sizes_in:
        raise LineError("En az bir boy seç.")
    record["sizes_in"] = sorted(sizes_in)
    record["kit"] = None
    store.event(record, "boylar: " + ", ".join(f'{s:g}"' for s in record["sizes_in"]))
    store.save(record)
    return record


# --- 2. cut check + vector ------------------------------------------------------------------------

def edit_info(record: dict) -> dict | None:
    """The edit steps in use: only those made on the currently chosen candidate."""
    edit = record.get("edit")
    if edit and edit.get("base") == record.get("chosen") and edit.get("versions"):
        return edit
    return None


def design_state(record: dict) -> str:
    """Which version of the design is in use: the latest edit step's file, or "" for the original."""
    edit = edit_info(record)
    return edit["versions"][-1]["file"] if edit else ""


def mockups_stale(record: dict) -> bool:
    """Listing images made from another version of the design than the one in use now."""
    return bool(record.get("mockups")) and record.get("mockups_from", "") != design_state(record)


def base_mask(record: dict, width_mm: float, speck_mm2: float) -> np.ndarray:
    """The cut mask before the clock hub: the latest edit when there is one, else the cleaned candidate.
    Cropped to the metal, specks removed at the given width."""
    folder = store.design_dir(record["id"])
    edit = edit_info(record)
    if edit:
        mask = raster.load_mask(folder / edit["versions"][-1]["file"])
    else:
        mask = raster.prepare(folder / record["chosen"])
    return raster.crop(cutcheck.remove_specks_mm(mask, mask.shape[1] / width_mm, speck_mm2))


def with_hub(record: dict, mask: np.ndarray, width_mm: float, cut: dict) -> np.ndarray:
    """Clocks get the solid hub and the shaft hole at the centre (exact, whatever the design has there)."""
    if record["product_type"] != "saat":
        return mask
    return compose.add_clock_hub(mask, width_mm, cut["clock_hub_frac"], cut["clock_hole_mm"])


def hub_geometry(record: dict, shape: tuple[int, int], width_mm: float) -> dict | None:
    """Where with_hub puts the hub on a mask of this shape (for the editor to draw)."""
    if record["product_type"] != "saat":
        return None
    cut = config.load_settings()["cut"]
    h, w = shape
    return {"cx": (w - 1) / 2, "cy": (h - 1) / 2, "r": cut["clock_hub_frac"] * min(h, w) / 2,
            "hole": cut["clock_hole_mm"] / 2 * w / width_mm}


def run_check(record: dict, width_in: float, multi_piece: bool = False, reason: str = "",
              overrides: dict | None = None) -> dict:
    if not record.get("chosen"):
        raise LineError("Önce bir aday seç ya da tasarım yükle.")
    settings = config.load_settings()
    cut = {**settings["cut"], **(overrides or {})}
    width_mm = float(width_in) * 25.4
    folder = store.design_dir(record["id"])
    params = cutcheck.Params(
        width_mm=width_mm, thickness_mm=float(settings["facts"].get("thickness_mm") or cut["thickness_mm"]),
        min_width_mm=float(cut["min_width_mm"]), min_hole_mm=float(cut["min_hole_mm"]),
        min_gap_mm=float(cut["min_gap_mm"]), speck_mm2=float(cut["speck_mm2"]), multi_piece=multi_piece,
    )
    base = base_mask(record, width_mm, cut["speck_mm2"])
    mask = with_hub(record, with_text(record, base, params), width_mm, cut)
    result = cutcheck.check(mask, params)
    raster.to_image(mask).save(folder / MASTER)
    if (folder / FIXES).exists():
        shutil.rmtree(folder / FIXES)
    # the name plate is drawn by code: its spots get no fix cards (a longer name or a bigger size fixes them)
    plate_from = base.shape[0] if mask.shape[0] > base.shape[0] else None
    fixes = onarim.analyze(mask, params, result, folder / FIXES, FIXES, skip_from=plate_from)
    overlay = cutcheck.overlay(mask, result)
    onarim.label_overlay(overlay, mask.shape, fixes, mockup.font("Inter.ttf", 22)).save(folder / OVERLAY)
    (folder / SVG).write_text(vector.to_svg(mask, width_mm), encoding="utf-8")
    write_dxf(record, trace_for_dxf(record, mask), width_mm, folder / DXF)
    record["check"] = {
        "at": store.now(), "ok": result.ok, "width_in": float(width_in),
        "params": params.__dict__, "findings": result.findings, "stats": result.stats, "fixes": fixes,
    }
    record["multi_piece"] = {"allowed": multi_piece, "reason": reason.strip()}
    record["vector"] = SVG
    store.event(record, f"kontrol: {'GEÇTİ' if result.ok else 'HATA'} ({width_in:g} in genişlik)")
    store.save(record)
    return record


def master_mask(record: dict) -> np.ndarray:
    path = store.design_dir(record["id"]) / MASTER
    if not path.exists():
        raise LineError("Önce kesilebilirlik kontrolünü çalıştır.")
    return raster.load_mask(path)


# --- 2b. fixes and edits ---------------------------------------------------------------------------
# Every fix or editor save is a new edit step: a full cut mask without the clock hub, saved under
# duzenleme/. The latest step replaces the candidate as the check's source; undo drops the latest
# step, "original" drops them all. The check is re-run with the same settings after every change.

def _checked(record: dict) -> dict:
    if not record.get("check"):
        raise LineError("Önce kesilebilirlik kontrolünü çalıştır.")
    return record["check"]


def recheck(record: dict) -> dict:
    chk = _checked(record)
    p = chk["params"]
    run_check(record, chk["width_in"], bool(p.get("multi_piece")), (record.get("multi_piece") or {}).get("reason", ""),
              {"min_width_mm": p["min_width_mm"], "min_hole_mm": p["min_hole_mm"], "min_gap_mm": p["min_gap_mm"]})
    return refresh_preflight(record)


def save_edit(record: dict, mask: np.ndarray, note: str) -> None:
    folder = store.design_dir(record["id"])
    edit = edit_info(record)
    if not edit:  # first step on this candidate: steps made on another candidate go
        for old in (record.get("edit") or {}).get("versions", []):
            (folder / old["file"]).unlink(missing_ok=True)
        edit = {"base": record["chosen"], "versions": []}
    (folder / EDITS).mkdir(exist_ok=True)
    rel = f"{EDITS}/{len(edit['versions']) + 1:03d}-{datetime.now():%H%M%S%f}.png"
    raster.to_image(mask).save(folder / rel)
    edit["versions"].append({"file": rel, "at": store.now(), "note": note})
    record["edit"] = edit
    record["kit"] = None
    store.event(record, f"düzeltme: {note}")
    store.save(record)


def _save_change(record: dict, base: np.ndarray, master: np.ndarray, new_master: np.ndarray, note: str) -> None:
    """A change worked out on the checked mask (hub and name plate included) becomes an edit step of the
    design itself. The plate is below the design's rows and is drawn again by code, so it is left out."""
    h = base.shape[0]
    if master.shape[1] != base.shape[1] or master.shape[0] < h:
        raise LineError("Tasarım kontrolden sonra değişmiş — kontrolü yeniden çalıştır.")
    old, new = master[:h], new_master[:h]
    save_edit(record, (base | (new & ~old)) & ~(old & ~new), note)


def _fix_scene(record: dict) -> tuple[np.ndarray, np.ndarray, cutcheck.Params, cutcheck.Result, int | None]:
    """The checked mask, the design's own (editable) mask, the check, and where the name plate starts."""
    master = master_mask(record)
    params = cutcheck.Params(**_checked(record)["params"])
    base = base_mask(record, params.width_mm, params.speck_mm2)
    plate_from = base.shape[0] if master.shape[0] > base.shape[0] else None
    return master, base, params, cutcheck.check(master, params), plate_from


def apply_fix(record: dict, code: str, ref: tuple[int, int], key: str) -> str:
    master, base, params, res, plate_from = _fix_scene(record)
    if plate_from is not None and ref[0] >= plate_from:
        raise LineError("İsim plakası kodla çizilir; elle düzeltilmez. Uyarı varsa daha kısa isim ya da büyük boy seç.")
    try:
        new, title = onarim.apply_option(master, params, res, code, ref, key)
    except ValueError as exc:
        raise LineError(str(exc)) from exc
    cards = [c for g in (record["check"].get("fixes") or {}).get("groups", []) for c in g["cards"]]
    label = next((c["label"] for c in cards if c["code"] == code and c["ref"] == list(ref)), onarim.TITLES[code])
    _save_change(record, base, master, new, f"{label} {title.lower()}")
    recheck(record)
    return f"{label}: {title} uygulandı."


def apply_auto(record: dict, codes: list[str] | None = None) -> str:
    master, base, params, res, plate_from = _fix_scene(record)
    new, done = onarim.apply_auto(master, params, res, codes, skip_from=plate_from)
    if not done:
        raise LineError("Otomatik düzeltilecek bir şey yok.")
    what = ", ".join(onarim.TITLES[c].lower() for c in codes) if codes else "hepsi"
    _save_change(record, base, master, new, f"otomatik ({what}, {done} nokta)")
    recheck(record)
    return f"{done} nokta otomatik düzeltildi."


def undo_edit(record: dict) -> str:
    edit = edit_info(record)
    if not edit:
        raise LineError("Geri alınacak düzeltme yok.")
    last = edit["versions"].pop()
    (store.design_dir(record["id"]) / last["file"]).unlink(missing_ok=True)
    if not edit["versions"]:
        record["edit"] = None
    store.event(record, f"düzeltme geri alındı: {last['note']}")
    store.save(record)
    recheck(record)
    return f"Geri alındı: {last['note']}"


def revert_edits(record: dict) -> str:
    edit = edit_info(record)
    if not edit:
        raise LineError("Tasarım zaten orijinal halinde.")
    for v in edit["versions"]:
        (store.design_dir(record["id"]) / v["file"]).unlink(missing_ok=True)
    record["edit"] = None
    store.event(record, f"orijinale dönüldü ({len(edit['versions'])} düzeltme kaldırıldı)")
    store.save(record)
    recheck(record)
    return "Orijinal tasarıma dönüldü."


def editor_mask(record: dict) -> np.ndarray:
    p = _checked(record)["params"]
    return base_mask(record, p["width_mm"], p["speck_mm2"])


def editor_check(record: dict, mask: np.ndarray) -> dict:
    """The cut check of a mask straight from the editor, laid out on the editor's own canvas."""
    params = cutcheck.Params(**_checked(record)["params"])
    rows, cols = np.flatnonzero(mask.any(axis=1)), np.flatnonzero(mask.any(axis=0))
    if rows.size == 0:
        return {"ok": False, "findings": [{"level": "HATA", "code": "BOS", "msg": "Tasarımda metal kalmadı."}],
                "counts": {}, "marks": [], "layer": ""}
    y0, x0 = int(rows[0]), int(cols[0])
    m = mask[y0:rows[-1] + 1, x0:cols[-1] + 1]
    m = cutcheck.remove_specks_mm(m, m.shape[1] / params.width_mm, params.speck_mm2)
    m = with_hub(record, with_text(record, m, params), params.width_mm, config.load_settings()["cut"])
    res = cutcheck.check(m, params)
    counts: dict[str, int] = {}
    for code, _ in res.marks:
        counts[code] = counts.get(code, 0) + 1
    marks = [[code, b[0] + y0, b[1] + x0, b[2] + y0, b[3] + x0] for code, b in res.marks[:400]]
    return {"ok": res.ok, "findings": res.findings, "counts": counts, "marks": marks,
            "layer": onarim.problem_layer(mask.shape, res, (y0, x0))}


def editor_save(record: dict, mask: np.ndarray) -> str:
    if not mask.any():
        raise LineError("Tasarımda metal kalmadı — kaydedilmedi.")
    save_edit(record, mask, "düzenleyici")
    recheck(record)
    return "Düzenleme kaydedildi, kontrol yenilendi."


# --- 3. mockups -----------------------------------------------------------------------------------

CARDS = ("renkler", "boyut", "detay", "bilgi", "montaj", "kargo", "gumruk")  # Available Finishes, Size Guide,
# close-up, Details, then the shop's own ready-made ones — in this order
READY = {"montaj": "install", "kargo": "shipping", "gumruk": "customs"}  # card -> image kind, in card order;
# the file is config.READY_CARDS/<card>.png, uploaded in Ayarlar (a shipping or customs promise is the shop's
# own, so the program has none to offer)
READY_LABELS = {"montaj": "Montaj kartı", "kargo": "Kargo kartı", "gumruk": "Gümrük kartı"}
READY_LICENSE = "Kullanıcının hazır kartları (montaj, kargo, gümrük)"


def ready_cards() -> list[str]:
    """The ready-made cards this install has."""
    return [card for card in READY if (config.READY_CARDS / f"{card}.png").is_file()]


def save_ready_card(card: str, data: bytes, filename: str = "") -> None:
    if card not in READY:
        raise LineError("Böyle bir kart yok.")
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    except Exception as exc:  # PIL raises many types for bad files
        raise LineError(f"Görsel açılamadı ({filename}): {exc}") from exc
    config.READY_CARDS.mkdir(parents=True, exist_ok=True)
    img.save(config.READY_CARDS / f"{card}.png", "PNG")


def delete_ready_card(card: str) -> None:
    if card in READY:
        (config.READY_CARDS / f"{card}.png").unlink(missing_ok=True)


def room_plan(plan: dict) -> dict[str, list[str]]:
    """Rooms picked per colour: existing rooms only, no repeats within a colour, at most the colour's slots."""
    known = {r["id"] for r in rooms.list_rooms()}
    out = {}
    for fin, limit in mockup.SLOTS.items():
        picked = [r for r in dict.fromkeys(plan.get(fin) or []) if r in known]
        out[fin] = picked[:limit]
    return out


def render_mockups(record: dict, plan: dict, cards: list[str]) -> dict:
    """Listing images: every colour on the rooms the user picked for it (black 2, gold 2, the rest 1),
    in colour order, followed by the chosen cards."""
    if not record.get("check"):
        raise LineError("Önce kesilebilirlik kontrolünü çalıştır.")
    plan = room_plan(plan)
    have = ready_cards()
    cards = [c for c in CARDS if c in cards and (c not in READY or c in have)]
    jobs = [(fin, room_id, n) for fin in mockup.PALETTE for n, room_id in enumerate(plan[fin], start=1)]
    if not jobs and not cards:
        raise LineError("Bir renge oda seç ya da en az bir kart işaretle.")
    mask = master_mask(record)
    clock = record["product_type"] == "saat"
    settings = config.load_settings()
    design_sizes = sizes(record)
    # the sheet's real thickness against the design's width (at the checked, usually smallest, size):
    # the cut edge is drawn that thin, so 1.5 mm steel does not read as a 1 cm slab
    chk = record["check"]["params"]
    plate = float(settings["facts"].get("thickness_mm") or chk["thickness_mm"]) / chk["width_mm"]
    base = store.design_dir(record["id"])
    if (base / "mockup").exists():
        shutil.rmtree(base / "mockup")
    (base / "mockup").mkdir()
    out = [{"file": f"mockup/{i:02d}-{fin}-{n}.jpg", "kind": "room", "finish": fin, "room": room_id}
           for i, (fin, room_id, n) in enumerate(jobs, start=1)]

    # one worker per room: the photo is loaded once and every colour picked for it hangs on it
    by_room: dict[str, list[int]] = {}
    for i, (_, room_id, _) in enumerate(jobs):
        by_room.setdefault(room_id, []).append(i)

    def one_room(room_id: str) -> None:
        room = rooms.get(room_id)
        path = config.ROOMS / room["file"]
        bg, box = mockup.room_background(path, room["box"])
        scale = mockup.cover_scale(path)
        for i in by_room[room_id]:
            img = mockup.scene(mask, jobs[i][0], bg, box, clock=clock, bg_scale=scale, seed=3 + i, plate=plate)
            mockup.save_jpg(mockup.to_image(img), base / out[i]["file"])

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(one_room, by_room))
    for room_id in by_room:
        ai_room = rooms.get(room_id)["source"] == "ai"
        store.add_license(record, "AI ile üretilmiş oda fotoğrafları" if ai_room else "Kullanıcının kendi oda fotoğrafları")
        record["ai_used"] = record.get("ai_used") or ai_room

    def emit(img: Image.Image, name: str, kind: str) -> None:
        rel = f"mockup/{len(out) + 1:02d}-{name}.jpg"
        mockup.save_jpg(img, base / rel)
        out.append({"file": rel, "kind": kind})

    hero = mockup.PALETTE[0]
    if "renkler" in cards:
        emit(mockup.finishes_card(mask, list(mockup.PALETTE), clock=clock, plate=plate), "renkler", "finishes")
    if "boyut" in cards:
        emit(mockup.size_card(mask, design_sizes, clock=clock), "boyutlar", "sizes")
    if "detay" in cards:
        emit(mockup.detail_crop(mask, hero, mockup.FINISHES[hero]["wall"], clock=clock, plate=plate), "yakin", "detail")
    fonts = {"Playfair Display", "Inter"} if {"renkler", "boyut"} & set(cards) else set()
    if "bilgi" in cards:
        emit(mockup.info_card(mask, hero, settings["facts"], record["product_type"], design_sizes, plate=plate), "bilgi", "info")
        fonts.update(mockup.DETAILS_FONTS)
    for card, kind in READY.items():  # the same image on every listing, only brought to the listing size
        if card in cards:
            with Image.open(config.READY_CARDS / f"{card}.png") as img:
                img = img.convert("RGB")
                emit(ImageOps.pad(img, mockup.CANVAS, Image.LANCZOS, color=img.getpixel((0, 0))), card, kind)
            store.add_license(record, READY_LICENSE)
    if set(cards) - set(READY):
        store.add_license(record, "Kodla üretilmiş duvarlar")
    for name in sorted(fonts):
        store.add_license(record, name)
    record["mockups"] = out
    record["mockups_from"] = design_state(record)
    record["oda_plani"] = plan
    record["mockup_finishes"] = list(mockup.PALETTE)
    record["kit"] = None
    store.event(record, f"{len(out)} listing görseli üretildi ({len(jobs)} renk-oda + {len(cards)} kart)")
    store.save(record)
    return record


CARD_OF_KIND = {"finishes": "renkler", "sizes": "boyut", "detail": "detay", "info": "bilgi",
                **{kind: card for card, kind in READY.items()}}


def _image_key(item: dict) -> tuple:
    return ("room", item.get("finish"), item.get("room")) if item.get("kind") == "room" else (item.get("kind"),)


def refresh_mockups(record: dict) -> str:
    """The listing images made again from the design in use, as the set stands: the same colour-room pairs,
    the same cards and the user's order. Deleted images stay deleted."""
    old = list(record.get("mockups") or [])
    if not old:
        raise LineError("Yenilenecek görsel yok — önce görselleri oluştur.")
    plan: dict[str, list[str]] = {fin: [] for fin in mockup.PALETTE}
    for item in old:
        if item.get("kind") == "room" and item.get("finish") in plan:
            plan[item["finish"]].append(item["room"])
    cards = [CARD_OF_KIND[item["kind"]] for item in old if item.get("kind") in CARD_OF_KIND]
    render_mockups(record, plan, cards)
    order = {_image_key(item): i for i, item in enumerate(old)}
    record["mockups"].sort(key=lambda item: order.get(_image_key(item), len(old)))
    store.save(record)
    lost = len(old) - len(record["mockups"])
    return f"{len(record['mockups'])} görsel güncel tasarımla yenilendi." + (
        f" {lost} görselin odası ya da kartı artık yok, atlandı." if lost > 0 else "")


def move_mockup(record: dict, file: str, direction: int) -> dict:
    items = record.get("mockups") or []
    idx = next((i for i, m in enumerate(items) if m["file"] == file), None)
    if idx is None:
        raise LineError("Görsel bulunamadı.")
    j = max(0, min(len(items) - 1, idx + direction))
    items[idx], items[j] = items[j], items[idx]
    store.save(record)
    return record


def delete_mockup(record: dict, file: str) -> str:
    """Drop one listing image: out of the order and off the disk. The kit has to be made again."""
    items = record.get("mockups") or []
    item = next((m for m in items if m["file"] == file), None)
    if item is None:
        raise LineError("Görsel bulunamadı.")
    items.remove(item)
    (store.design_dir(record["id"]) / item["file"]).unlink(missing_ok=True)
    picked = (record.get("oda_plani") or {}).get(item.get("finish"))
    if item.get("kind") == "room" and picked and item.get("room") in picked:
        picked.remove(item["room"])  # the colour's mark leaves that room in the picker too
    record["kit"] = None
    store.event(record, f"listing görseli silindi: {item['file']}")
    store.save(record)
    return f"Görsel silindi, {len(items)} görsel kaldı."


# --- 4. listing -----------------------------------------------------------------------------------

def write_listing(record: dict, provider: str, keywords: str = "") -> dict:
    mask = master_mask(record)
    settings = config.load_settings()
    image_png = raster.png_bytes(raster.to_image(mask), max_edge=1024)
    labels = [f"{d['label_in']} ({d['label_cm']})" for d in size_dims(record)]
    data, info = listing.generate(record, image_png, provider, settings["facts"], labels, list(mockup.PALETTE), keywords,
                                  shop=settings["shop"], widths=sizes(record),
                                  style_example=settings["style_example"])
    record["listing"] = {**data, "keywords": keywords, "written_by": info, "at": store.now()}
    record["preflight"] = preflight.check(record)
    record["kit"] = None
    store.event(record, f"listing metni yazıldı ({info['provider']} · {info['model']})")
    store.save(record)
    return record


def save_listing(record: dict, title: str, tags_text: str, description: str) -> dict:
    tags = [t.strip().lower() for t in tags_text.replace("\n", ",").split(",") if t.strip()]
    base = record.get("listing") or {}
    record["listing"] = {**base, "title": title.strip(), "tags": tags, "description": description.strip().replace("\r\n", "\n"),
                         "edited": store.now()}
    record["preflight"] = preflight.check(record)
    record["kit"] = None
    store.event(record, "listing metni elle düzenlendi")
    store.save(record)
    return record


def refresh_preflight(record: dict) -> dict:
    if record.get("listing"):
        record["preflight"] = preflight.check(record)
        store.save(record)
    return record


# --- 5. kit ---------------------------------------------------------------------------------------

def export_kit(record: dict) -> Path:
    settings = config.load_settings()
    findings = preflight.check(record)
    record["preflight"] = findings
    if preflight.has_errors(findings):
        store.save(record)
        raise LineError("Preflight'ta HATA var — kit çıkmaz. Listing sekmesindeki kırmızı satırları düzelt.")
    if mockups_stale(record):
        raise LineError("Tasarım görseller yapıldıktan sonra düzeltildi — kit için görselleri yeniden oluştur.")
    folder = store.design_dir(record["id"])
    kit = folder / "kit"
    if kit.exists():
        shutil.rmtree(kit)
    (kit / "gorseller").mkdir(parents=True)
    (kit / "atolye").mkdir()
    for i, item in enumerate(record["mockups"], start=1):
        shutil.copy2(folder / item["file"], kit / "gorseller" / f"{i:02d}-{Path(item['file']).name.split('-', 1)[1]}")
    lst = record["listing"]
    chk = record["check"]
    size_list = size_dims(record)
    variations = "\n".join(d["variation"] for d in size_list)
    size_line = "; ".join(f"{d['label_in']} ({d['label_cm']})" for d in size_list)
    (kit / "listing.txt").write_text(
        f"SKU\n{record.get('sku') or ''}\n\n"
        f"SIZES (Etsy variations)\n{variations}\n\n"
        f"TITLE\n{lst['title']}\n\nTAGS (13)\n{', '.join(lst['tags'])}\n\nMATERIALS\n{', '.join(lst.get('materials', []))}\n\n"
        f"DESCRIPTION\n{lst['description']}\n\nALT TEXT (first photo)\n{lst.get('alt_text', '')}\n",
        encoding="utf-8",
    )
    shutil.copy2(folder / SVG, kit / "atolye" / SVG)
    mask = master_mask(record)
    traced = trace_for_dxf(record, mask)  # traced once, written at every sale size in real mm
    for d in size_list:
        w_mm = d["w_in"] * 25.4
        name = f"{record.get('sku') or record['id']}_{fmt_in(d['w_in'])}in_{w_mm:.0f}mm.dxf"
        write_dxf(record, traced, w_mm, kit / "atolye" / "dxf" / name)
    raster.to_image(mask).save(kit / "atolye" / "tasarim.png", dpi=(round(mask.shape[1] / (chk["params"]["width_mm"] / 25.4)),) * 2)
    s = chk["stats"]
    (kit / "atolye" / "olcu.txt").write_text(
        f"SKU: {record.get('sku') or '-'}\n"
        f"Tasarım: {record['name']} ({record['id']})\n"
        f"Ölçü (bu dosya): {s['width_mm']:.0f} x {s['height_mm']:.0f} mm\n"
        f"Satış boyları (oran sabit): {size_line}\n"
        f"Sac: {chk['params']['thickness_mm']:g} mm · tahmini ağırlık {s['weight_kg_steel']} kg · kesim boyu ~{s['cut_length_m']} m · {s['pierces']} delme\n"
        f"Siyah = kalan metal. Kontrol eşikleri: köprü {chk['params']['min_width_mm']:g} mm, delik {chk['params']['min_hole_mm']:g} mm, boşluk {chk['params']['min_gap_mm']:g} mm\n"
        + "DXF: dxf/ klasöründe her satış boyu için ayrı dosya; mm, gerçek ölçü, ölçekleme gerekmez. "
          "Konturlar KESIM katmanında kapalı polyline.\n"
        + (f"SVG ve PNG yalnız {chk['width_in']:g} in boyundadır; başka boy için DXF'i kullan.\n")
        + ("Saat: göbek + mekanizma deliği Ø{:g} mm merkezde; DXF'lerde her boyda tam daire (CIRCLE).\n".format(settings['cut']['clock_hole_mm']) if record['product_type'] == 'saat' else ""),
        encoding="utf-8",
    )
    record["kit"] = {"at": store.now(), "path": str(kit).replace("\\", "/")}
    store.event(record, "yükleme kiti çıkarıldı")
    store.save(record)
    (kit / "kayit.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return kit
