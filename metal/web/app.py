"""Local panel (127.0.0.1 only). Every POST runs one line step, then redirects back (PRG)."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit

import numpy as np
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from .. import config, hat, mockup, preflight, providers, raster, rooms, store
from .. import sizes as boylar
from ..providers import usage

HERE = Path(__file__).resolve().parent
app = FastAPI(title="Etsy Metal Paneli", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

LOCAL_HOSTS = {"127.0.0.1", "localhost"}


@app.middleware("http")
async def local_only(request: Request, call_next):
    """The panel has no login and can spend the AI budget, so only its own pages on this computer may use it:
    a foreign Host name (DNS rebinding) or a request sent by another website's page is refused."""
    origin = request.headers.get("origin")
    foreign = origin is not None and urlsplit(origin).netloc != request.headers.get("host")
    if request.url.hostname not in LOCAL_HOSTS or foreign:
        return Response("Bu panel yalnız bu bilgisayardan kullanılır.", status_code=403, media_type="text/plain; charset=utf-8")
    return await call_next(request)


INSTALL_ID = hashlib.sha1(str(config.ROOT).encode()).hexdigest()[:12]  # tells two copies on one computer apart


@app.get("/api/panel")
def api_panel():
    """What the starter asks before opening the browser: is this install's panel already running here?"""
    return {"app": "etsy-metal", "install": INSTALL_ID}

templates = Jinja2Templates(directory=HERE / "templates")


def _asset_version(name: str) -> str:
    """Static file mtime as a cache-busting query, so the browser never runs a stale app.js/app.css."""
    return str(int((HERE / "static" / name).stat().st_mtime))


templates.env.globals["asset_v"] = _asset_version
templates.env.filters["g"] = lambda v: f"{float(v):g}"  # 24.0 -> "24", 12.5 -> "12.5"

USER_ERRORS = (hat.LineError, providers.ProviderError, providers.BudgetError, ValueError)


def _go(url: str, ok: str = "", err: str = "", anchor: str = "") -> RedirectResponse:
    params = []
    if ok:
        params.append(f"ok={quote(ok)}")
    if err:
        params.append(f"err={quote(err)}")
    target = url + ("?" + "&".join(params) if params else "") + (f"#{anchor}" if anchor else "")
    return RedirectResponse(target, status_code=303)


def _ctx(request: Request, **extra) -> dict:
    settings = config.load_settings()
    return {
        "request": request,
        "settings": settings,
        "spent": usage.month_total(),
        "budget": settings["monthly_budget_usd"],
        "ok": request.query_params.get("ok", ""),
        "err": request.query_params.get("err", ""),
        "product_types": store.PRODUCT_TYPES,
        "providers": providers.PROVIDERS,
        "finishes": mockup.FINISHES,
        "palette": mockup.PALETTE,
        "slots": mockup.SLOTS,
        "ocr_ready": bool(boylar.tesseract()),
        "ocr_hint": boylar.install_hint(),
        "ready_cards": {c: hat.READY_LABELS[c] for c in hat.ready_cards()},
        "keys": {p: bool(config.get_key(p)) for p in providers.PROVIDERS},
        **extra,
    }


# --- pages ----------------------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    store.backfill_skus()
    designs = store.list_all()
    for d in designs:
        d["_stage"] = store.stage(d)
        d["_thumb"] = store.thumb(d)
    return templates.TemplateResponse(request, "index.html", _ctx(request, designs=designs, stages=dict(store.STAGES)))


@app.get("/yeni", response_class=HTMLResponse)
def new_page(request: Request):
    return templates.TemplateResponse(request, "yeni.html", _ctx(request))


@app.get("/t/{design_id}", response_class=HTMLResponse)
def design_page(request: Request, design_id: str):
    try:
        record = store.load(design_id)
    except (FileNotFoundError, ValueError):
        return _go("/", err="Tasarım bulunamadı.")
    findings = record.get("preflight") or []
    sizes = hat.sizes(record)
    return templates.TemplateResponse(request, "tasarim.html", _ctx(
        request, r=record, stage=store.stage(record), stages=store.STAGES,
        rooms=rooms.list_rooms(), sizes=sizes, default_width=min(sizes),
        aspect=hat.aspect(record), size_rows=hat.size_dims(record),
        has_dxf=(store.design_dir(design_id) / hat.DXF).exists(), edit=hat.edit_info(record), mockups_stale=hat.mockups_stale(record),
        plan=hat.room_plan(record.get("oda_plani") or {}),
        pf_errors=preflight.has_errors(findings) if record.get("listing") else True,
    ))


@app.get("/odalar", response_class=HTMLResponse)
def rooms_page(request: Request):
    return templates.TemplateResponse(request, "odalar.html", _ctx(request, rooms=rooms.list_rooms(), presets=rooms.ROOM_PRESETS))


@app.get("/ayarlar", response_class=HTMLResponse)
def settings_page(request: Request):
    return templates.TemplateResponse(request, "ayarlar.html", _ctx(
        request, masked={p: config.masked_key(p) for p in providers.PROVIDERS}, breakdown=usage.month_breakdown(),
        card_slots=hat.READY_LABELS,
        card_v={c: int((config.READY_CARDS / f"{c}.png").stat().st_mtime) for c in hat.ready_cards()},
    ))


# --- files ----------------------------------------------------------------------------------------

@app.get("/f/{design_id}/{path:path}")
def design_file(design_id: str, path: str):
    base = store.design_dir(design_id).resolve()
    target = (base / path).resolve()
    if base not in target.parents or not target.is_file():
        return JSONResponse({"error": "yok"}, status_code=404)
    return FileResponse(target, headers={"Cache-Control": "no-cache"})


@app.get("/oda/{file}")
def room_file(file: str):
    target = (config.ROOMS / file).resolve()
    if config.ROOMS.resolve() not in target.parents or not target.is_file():
        return JSONResponse({"error": "yok"}, status_code=404)
    return FileResponse(target)


@app.get("/kart/{card}")
def ready_card_file(card: str):
    if card not in hat.ready_cards():
        return JSONResponse({"error": "yok"}, status_code=404)
    return FileResponse(config.READY_CARDS / f"{card}.png", headers={"Cache-Control": "no-cache"})


# --- design actions -------------------------------------------------------------------------------

NO_TYPE = "Ürün tipini seç (Saat, Duvar süsü…) — saat seçilirse göbek, mekanizma deliği ve akrep-yelkovan eklenir."


@app.post("/yeni")
def new_design(product_type: str = Form(""), brief: str = Form(...), name: str = Form(""),
               provider: str = Form("gemini"), model: str = Form(""), n: int = Form(3), sample_text: str = Form(""),
               sizes_in: list[str] = Form([])):
    if product_type not in store.PRODUCT_TYPES:
        return _go("/yeni", err=NO_TYPE)
    record = store.create(product_type, brief, name, sizes_in=config.parse_sizes(sizes_in))
    if sample_text.strip():
        record["sample_text"] = sample_text.strip()
        store.save(record)
    try:
        hat.generate(record, provider, n, model=model.strip() or None, sample_text=sample_text)
    except USER_ERRORS as exc:
        return _go(f"/t/{record['id']}", err=str(exc), anchor="adaylar")
    return _go(f"/t/{record['id']}", ok="Adaylar hazır — beğendiğini seç.", anchor="adaylar")


@app.post("/yukle")
def upload_design(product_type: str = Form(""), name: str = Form(""), brief: str = Form(""), file: UploadFile = File(...),
                  sizes_in: list[str] = Form([])):
    if product_type not in store.PRODUCT_TYPES:
        return _go("/yeni", err=NO_TYPE, anchor="yukle")
    record = store.create(product_type, brief or name, name or Path(file.filename or "tasarim").stem, source="upload",
                          sizes_in=config.parse_sizes(sizes_in))
    try:
        hat.upload(record, file.file.read(), file.filename or "tasarim")
    except USER_ERRORS as exc:
        return _go(f"/t/{record['id']}", err=str(exc))
    return _go(f"/t/{record['id']}", ok="Tasarım yüklendi — şimdi kesilebilirlik kontrolü.", anchor="kontrol")


# --- custom portraits -----------------------------------------------------------------------------

@app.post("/portre")
async def new_portrait(file: UploadFile = File(...), note: str = Form(""), text: str = Form(""), aspect: str = Form("dikey"),
                       name: str = Form(""), provider: str = Form("gemini"), n: int = Form(3), sizes_in: list[str] = Form([])):
    data = await file.read()
    record = store.create("portre", note, name.strip() or "Özel portre", source="ai", sizes_in=config.parse_sizes(sizes_in))
    try:
        hat.start_portrait(record, data, file.filename or "foto", text, aspect)
        await run_in_threadpool(hat.generate, record, provider, n)
    except USER_ERRORS as exc:
        return _go(f"/t/{record['id']}", err=str(exc), anchor="adaylar")
    return _go(f"/t/{record['id']}", ok="Portre adayları hazır — en benzeyeni seç.", anchor="adaylar")


@app.post("/t/{design_id}/foto")
async def portrait_photo(design_id: str, file: UploadFile = File(...)):
    record = store.load(design_id)
    try:
        hat.set_photo(record, await file.read(), file.filename or "foto")
        store.save(record)
    except USER_ERRORS as exc:
        return _go(f"/t/{design_id}", err=str(exc), anchor="adaylar")
    return _go(f"/t/{design_id}", ok="Fotoğraf değişti — yeni adaylar için \"Üret\".", anchor="adaylar")


@app.post("/t/{design_id}/yazi")
async def plate_text(design_id: str, text: str = Form("")):
    record = store.load(design_id)
    try:
        msg = await run_in_threadpool(hat.set_text, record, text)
    except USER_ERRORS as exc:
        return _go(f"/t/{design_id}", err=str(exc), anchor="yazi")
    return _go(f"/t/{design_id}", ok=msg, anchor="yazi")


@app.post("/t/{design_id}/siparis")
async def open_order(design_id: str, text: str = Form(""), file: UploadFile | None = File(None),
                     provider: str = Form("gemini"), n: int = Form(3)):
    record = store.load(design_id)
    photo = await file.read() if file is not None and file.filename else None
    try:
        order = await run_in_threadpool(hat.open_order, record, text, photo, file.filename if photo else "", provider, n)
    except USER_ERRORS as exc:
        return _go(f"/t/{design_id}", err=str(exc), anchor="yazi")
    msg = (f"Sipariş {order['sku']} açıldı: yeni portre adayları hazır, en benzeyeni seç." if photo else
           f"Sipariş {order['sku']} açıldı: aynı portre, isim \"{hat.plate_text(order)}\".")
    return _go(f"/t/{order['id']}", ok=msg, anchor="adaylar" if photo else "yazi")


@app.post("/t/{design_id}/uret")
def more_candidates(design_id: str, brief: str = Form(""), provider: str = Form("gemini"), model: str = Form(""),
                    n: int = Form(3), sample_text: str = Form("")):
    record = store.load(design_id)
    try:
        hat.generate(record, provider, n, brief=brief, model=model.strip() or None,
                     sample_text=sample_text or record.get("sample_text", ""))
    except USER_ERRORS as exc:
        return _go(f"/t/{design_id}", err=str(exc), anchor="adaylar")
    return _go(f"/t/{design_id}", ok="Yeni adaylar eklendi.", anchor="adaylar")


@app.post("/t/{design_id}/yukle")
def upload_candidate(design_id: str, file: UploadFile = File(...)):
    record = store.load(design_id)
    try:
        hat.upload(record, file.file.read(), file.filename or "tasarim")
    except USER_ERRORS as exc:
        return _go(f"/t/{design_id}", err=str(exc), anchor="adaylar")
    return _go(f"/t/{design_id}", ok="Yüklendi ve seçildi.", anchor="kontrol")


@app.post("/t/{design_id}/sec")
def choose(design_id: str, candidate: str = Form(...)):
    record = store.load(design_id)
    try:
        hat.choose(record, candidate)
    except USER_ERRORS as exc:
        return _go(f"/t/{design_id}", err=str(exc), anchor="adaylar")
    return _go(f"/t/{design_id}", ok="Seçildi — kesilebilirlik kontrolünü çalıştır.", anchor="kontrol")


@app.post("/t/{design_id}/ad")
def rename(design_id: str, name: str = Form(...)):
    record = store.load(design_id)
    record["name"] = name.strip() or record["name"]
    store.save(record)
    return _go(f"/t/{design_id}")


@app.post("/t/{design_id}/sku")
def set_sku(design_id: str, sku: str = Form("")):
    record = store.load(design_id)
    try:
        store.set_sku(record, sku)
    except ValueError as exc:
        return _go(f"/t/{design_id}", err=str(exc))
    return _go(f"/t/{design_id}", ok=f"SKU: {record['sku']}")


@app.post("/t/{design_id}/boylar")
def set_sizes(design_id: str, sizes_in: list[str] = Form([])):
    record = store.load(design_id)
    try:
        hat.set_sizes(record, config.parse_sizes(sizes_in))
    except USER_ERRORS as exc:
        return _go(f"/t/{design_id}", err=str(exc), anchor="boylar")
    return _go(f"/t/{design_id}", ok="Boylar kaydedildi — Size Guide ve bilgi kartı için görselleri yeniden oluştur.", anchor="boylar")


@app.post("/t/{design_id}/tip")
def set_product_type(design_id: str, product_type: str = Form("")):
    record = store.load(design_id)
    try:
        msg = hat.set_product_type(record, product_type)
    except USER_ERRORS as exc:
        return _go(f"/t/{design_id}", err=str(exc))
    return _go(f"/t/{design_id}", ok=msg)


@app.post("/api/boylar/ayikla")
def api_parse_sizes(text: str = Form("")):
    return {"rows": boylar.parse_text(text)}


@app.post("/api/boylar/oku")
def api_read_sizes(file: UploadFile = File(...)):
    try:
        text = boylar.ocr_text(file.file.read())
    except boylar.OcrError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return {"rows": boylar.parse_text(text), "text": text}


@app.post("/t/{design_id}/sil")
def delete_design(design_id: str):
    try:
        record = store.load(design_id)
    except (FileNotFoundError, ValueError):
        return _go("/", err="Tasarım bulunamadı.")
    store.delete(design_id)
    return _go("/", ok=f"{record.get('sku') or record['name']} silindi; SKU boşa çıktı.")


@app.post("/t/{design_id}/kontrol")
def run_check(design_id: str, width_in: float = Form(...), min_width_mm: float = Form(...), min_hole_mm: float = Form(...),
              min_gap_mm: float = Form(...), multi_piece: str = Form(""), reason: str = Form("")):
    record = store.load(design_id)
    try:
        hat.run_check(record, width_in, bool(multi_piece), reason,
                      {"min_width_mm": min_width_mm, "min_hole_mm": min_hole_mm, "min_gap_mm": min_gap_mm})
        hat.refresh_preflight(record)
    except USER_ERRORS as exc:
        return _go(f"/t/{design_id}", err=str(exc), anchor="kontrol")
    msg = "Kontrol geçti." if record["check"]["ok"] else "Kontrolde HATA var — aşağıdaki düzeltmelerden seç ya da düzenleyicide düzelt."
    return _go(f"/t/{design_id}", ok=msg if record["check"]["ok"] else "", err="" if record["check"]["ok"] else msg, anchor="kontrol")


# --- fixes and the editor -------------------------------------------------------------------------

def _fix_go(design_id: str, action) -> RedirectResponse:
    record = store.load(design_id)
    try:
        msg = action(record)
    except USER_ERRORS as exc:
        return _go(f"/t/{design_id}", err=str(exc), anchor="onarim")
    return _go(f"/t/{design_id}", ok=msg, anchor="onarim")


@app.post("/t/{design_id}/onarim")
def apply_fix(design_id: str, code: str = Form(...), y: int = Form(...), x: int = Form(...), option: str = Form(...)):
    return _fix_go(design_id, lambda r: hat.apply_fix(r, code, (y, x), option))


@app.post("/t/{design_id}/onarim/otomatik")
def apply_auto_fixes(design_id: str, code: list[str] = Form([])):
    return _fix_go(design_id, lambda r: hat.apply_auto(r, [c for c in code if c] or None))


@app.post("/t/{design_id}/onarim/geri")
def undo_fix(design_id: str):
    return _fix_go(design_id, hat.undo_edit)


@app.post("/t/{design_id}/onarim/orijinal")
def revert_fixes(design_id: str):
    return _fix_go(design_id, hat.revert_edits)


@app.get("/t/{design_id}/duzenle", response_class=HTMLResponse)
def editor_page(request: Request, design_id: str):
    try:
        record = store.load(design_id)
    except (FileNotFoundError, ValueError):
        return _go("/", err="Tasarım bulunamadı.")
    if not record.get("check"):
        return _go(f"/t/{design_id}", err="Düzenleyici için önce kesilebilirlik kontrolünü çalıştır.", anchor="kontrol")
    p = record["check"]["params"]
    shape = hat.editor_mask(record).shape
    cfg = {
        "id": design_id, "w": shape[1], "h": shape[0], "widthMm": p["width_mm"],
        "minWidth": p["min_width_mm"], "minGap": p["min_gap_mm"], "minHole": p["min_hole_mm"],
        "hub": hat.hub_geometry(record, shape, p["width_mm"]),
        "focus": [int(request.query_params["y"]), int(request.query_params["x"])]
        if request.query_params.get("y", "").isdigit() and request.query_params.get("x", "").isdigit() else None,
    }
    return templates.TemplateResponse(request, "duzenle.html", _ctx(request, r=record, cfg=cfg, edit=hat.edit_info(record)))


@app.get("/t/{design_id}/duzenle/maske.png")
def editor_mask_png(design_id: str):
    record = store.load(design_id)
    try:
        png = raster.png_bytes(raster.to_image(hat.editor_mask(record)))
    except USER_ERRORS as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


async def _posted_mask(request: Request) -> np.ndarray:
    """The editor sends its mask as packed bits (1 = metal, row by row, high bit first) with w and h."""
    try:
        w, h = int(request.query_params["w"]), int(request.query_params["h"])
    except (KeyError, ValueError) as exc:
        raise ValueError("maske ölçüsü eksik") from exc
    if not (8 <= w <= 8000 and 8 <= h <= 8000):
        raise ValueError("maske ölçüsü geçersiz")
    data = await request.body()
    if len(data) != (w * h + 7) // 8:
        raise ValueError("maske verisi eksik ya da fazla")
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8))[: w * h].reshape(h, w).astype(bool)


@app.post("/t/{design_id}/duzenle/kontrol")
async def editor_check(design_id: str, request: Request):
    record = store.load(design_id)
    try:
        mask = await _posted_mask(request)
        return await run_in_threadpool(hat.editor_check, record, mask)
    except USER_ERRORS as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@app.post("/t/{design_id}/duzenle/kaydet")
async def editor_save(design_id: str, request: Request):
    record = store.load(design_id)
    try:
        mask = await _posted_mask(request)
        msg = await run_in_threadpool(hat.editor_save, record, mask)
    except USER_ERRORS as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return {"url": f"/t/{design_id}?ok={quote(msg)}#onarim"}


@app.post("/t/{design_id}/mockup")
async def make_mockups(design_id: str, request: Request):
    form = await request.form()
    record = store.load(design_id)
    # oda_<colour> = "roomId,roomId" written by the colour/room picker
    plan = {fin: [r for r in str(form.get(f"oda_{fin}", "")).split(",") if r] for fin in mockup.PALETTE}
    try:
        await run_in_threadpool(hat.render_mockups, record, plan, form.getlist("card"))
        hat.refresh_preflight(record)
    except USER_ERRORS as exc:
        return _go(f"/t/{design_id}", err=str(exc), anchor="mockup")
    return _go(f"/t/{design_id}", ok=f"{len(record['mockups'])} görsel hazır.", anchor="mockup")


@app.post("/t/{design_id}/mockup/yenile")
async def refresh_mockups(design_id: str):
    record = store.load(design_id)
    try:
        msg = await run_in_threadpool(hat.refresh_mockups, record)
        hat.refresh_preflight(record)
    except USER_ERRORS as exc:
        return _go(f"/t/{design_id}", err=str(exc), anchor="mockup")
    return _go(f"/t/{design_id}", ok=msg, anchor="mockup")


@app.post("/t/{design_id}/mockup/sira")
def reorder(design_id: str, file: str = Form(...), direction: int = Form(...)):
    record = store.load(design_id)
    try:
        hat.move_mockup(record, file, direction)
        hat.refresh_preflight(record)
    except USER_ERRORS as exc:
        return _go(f"/t/{design_id}", err=str(exc), anchor="mockup")
    return _go(f"/t/{design_id}")  # no anchor: the page keeps its scroll position (data-keep-scroll)


@app.post("/t/{design_id}/mockup/sil")
def delete_mockup(design_id: str, file: str = Form(...)):
    record = store.load(design_id)
    try:
        hat.delete_mockup(record, file)
        hat.refresh_preflight(record)
    except USER_ERRORS as exc:
        return _go(f"/t/{design_id}", err=str(exc), anchor="mockup")
    return _go(f"/t/{design_id}")  # no banner or anchor: the page stays where it was


@app.post("/t/{design_id}/listing")
def write_listing(design_id: str, provider: str = Form("gemini"), keywords: str = Form("")):
    record = store.load(design_id)
    try:
        hat.write_listing(record, provider, keywords)
    except USER_ERRORS as exc:
        return _go(f"/t/{design_id}", err=str(exc), anchor="listing")
    return _go(f"/t/{design_id}", ok="Listing metni yazıldı — preflight sonucuna bak.", anchor="listing")


@app.post("/t/{design_id}/listing/kaydet")
def save_listing(design_id: str, title: str = Form(""), tags: str = Form(""), description: str = Form("")):
    record = store.load(design_id)
    hat.save_listing(record, title, tags, description)
    return _go(f"/t/{design_id}", ok="Kaydedildi, preflight yenilendi.", anchor="listing")


@app.post("/t/{design_id}/kit")
def export_kit(design_id: str):
    record = store.load(design_id)
    try:
        hat.export_kit(record)
    except USER_ERRORS as exc:
        return _go(f"/t/{design_id}", err=str(exc), anchor="kit")
    return _go(f"/t/{design_id}", ok="Kit hazır — Etsy'ye yükleyip yayınlamak sende.", anchor="kit")


def show_folder(folder: Path) -> None:
    """Open a folder in Explorer / Finder / the Linux file manager."""
    if hasattr(os, "startfile"):
        os.startfile(folder)  # type: ignore[attr-defined]  # Windows
    else:
        try:
            subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", str(folder)], check=False, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass  # no file manager (a server, a container): the path is on the page


@app.post("/t/{design_id}/klasor")
def open_folder(design_id: str, sub: str = Form("")):
    folder = store.design_dir(design_id) / sub if sub in ("", "kit", "mockup", "kit/atolye") else store.design_dir(design_id)
    if folder.exists():
        show_folder(folder)
    return _go(f"/t/{design_id}", anchor="kit")


# --- rooms ----------------------------------------------------------------------------------------

@app.post("/odalar/yukle")
def room_upload(name: str = Form(""), files: list[UploadFile] = File(...)):
    added, failed = 0, []
    for i, file in enumerate(files, start=1):
        label = (f"{name}-{i}" if len(files) > 1 else name) if name else Path(file.filename or "oda").stem
        try:
            rooms.add(file.file.read(), "upload", label)
            added += 1
        except Exception:  # bad image: report, keep going
            failed.append(file.filename or "?")
    if failed:
        return _go("/odalar", ok=f"{added} oda eklendi." if added else "", err=f"Açılamayan dosyalar: {', '.join(failed)}")
    return _go("/odalar", ok=f"{added} oda eklendi — yerleşim kutularını kontrol et (sürükleyerek düzeltilir).")


@app.post("/odalar/uret")
def room_generate(preset: str = Form(...), wall_note: str = Form(""), provider: str = Form("gemini"), name: str = Form("")):
    prompt = rooms.room_prompt(preset, wall_note)
    try:
        images, info = providers.generate_images(provider, prompt, 1, "1:1")  # listing images are square
    except USER_ERRORS as exc:
        return _go("/odalar", err=str(exc))
    rooms.add(images[0], "ai", name or preset, prompt=prompt, provider=info["provider"], model=info["model"])
    return _go("/odalar", ok="AI odası eklendi — yerleşim kutusunu kontrol et.")


@app.post("/odalar/{room_id}/kutu")
def room_box(room_id: str, x0: float = Form(...), y0: float = Form(...), x1: float = Form(...), y1: float = Form(...)):
    try:
        rooms.set_box(room_id, [x0, y0, x1, y1])
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"ok": True})


@app.post("/odalar/{room_id}/sifirla")
def room_box_reset(room_id: str):
    return JSONResponse({"box": rooms.reset_box(room_id)})


@app.post("/odalar/{room_id}/sil")
def room_delete(room_id: str):
    rooms.delete(room_id)
    return _go("/odalar", ok="Oda silindi.")


# --- settings -------------------------------------------------------------------------------------

@app.post("/ayarlar/anahtar")
def save_keys(openai_key: str = Form(""), gemini_key: str = Form("")):
    if openai_key.strip():
        config.set_key("openai", openai_key)
    if gemini_key.strip():
        config.set_key("gemini", gemini_key)
    return _go("/ayarlar", ok="Anahtarlar .env dosyasına kaydedildi.")


@app.post("/ayarlar/kart/{card}")
def upload_ready_card(card: str, file: UploadFile = File(...)):
    try:
        hat.save_ready_card(card, file.file.read(), file.filename or "kart")
    except USER_ERRORS as exc:
        return _go("/ayarlar", err=str(exc), anchor="kartlar")
    return _go("/ayarlar", ok=f"{hat.READY_LABELS[card]} kaydedildi.", anchor="kartlar")


@app.post("/ayarlar/kart/{card}/sil")
def delete_ready_card(card: str):
    hat.delete_ready_card(card)
    return _go("/ayarlar", ok="Kart silindi.", anchor="kartlar")


@app.get("/api/modeller/{provider}")
def api_models(provider: str):
    if provider not in providers.PROVIDERS:
        return JSONResponse({"error": "bilinmeyen sağlayıcı"}, status_code=400)
    try:
        return providers.list_models(provider)
    except providers.ProviderError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@app.post("/ayarlar")
async def save_settings(request: Request):
    form = await request.form()
    s = config.load_settings()

    def num(key: str, default: float) -> float:
        try:
            return float(str(form.get(key, default)).replace(",", "."))
        except ValueError:
            return default

    s["image_provider"] = form.get("image_provider", s["image_provider"])
    s["text_provider"] = form.get("text_provider", s["text_provider"])
    for p in providers.PROVIDERS:
        for kind in ("image", "text"):
            value = str(form.get(f"model_{p}_{kind}", "")).strip()
            if value:
                s["models"][p][kind] = value
    s["openai_image_quality"] = form.get("openai_image_quality", s["openai_image_quality"])
    s["monthly_budget_usd"] = num("monthly_budget_usd", s["monthly_budget_usd"])
    for key in ("min_width_mm", "min_hole_mm", "min_gap_mm", "clock_hole_mm"):
        s["cut"][key] = num(key, s["cut"][key])
    sizes = config.parse_sizes([], str(form.get("sizes_in", "")))
    if sizes:
        s["sizes_in"] = sizes
    s["sku_prefix"] = re.sub(r"[^A-Z0-9._-]", "", str(form.get("sku_prefix", s["sku_prefix"])).upper())[:12]
    if s["sku_prefix"] and not s["sku_prefix"][0].isalnum():
        s["sku_prefix"] = s["sku_prefix"].lstrip("._-")
    s["sku_start"] = max(1, int(num("sku_start", s["sku_start"])))
    s["style_example"] = str(form.get("style_example", s["style_example"])).strip().replace("\r\n", "\n")
    for key in ("name", "slogan", "story"):
        s["shop"][key] = str(form.get(f"shop_{key}", s["shop"].get(key, ""))).strip()
    facts = s["facts"]
    for key in ("material", "coating", "mounting", "clock_movement", "personalization", "processing_time",
                "ships_from", "indoor_outdoor", "care"):
        facts[key] = str(form.get(f"fact_{key}", facts.get(key, ""))).strip()
    facts["thickness_mm"] = num("fact_thickness_mm", facts.get("thickness_mm", 1.5))
    s["cut"]["thickness_mm"] = facts["thickness_mm"]
    facts["clock_hands_included"] = bool(form.get("fact_clock_hands_included"))
    config.save_settings(s)
    return _go("/ayarlar", ok="Ayarlar kaydedildi.")
