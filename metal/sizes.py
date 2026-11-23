"""Sale sizes. A size is a width in inches; the design's own proportions give the height, so every label
(Size Guide, listing, kit, workshop note) states the real piece. Widths can be typed in inches or cm, pasted
as text, or read from a screenshot of a size list with Tesseract (local, free OCR; no AI service)."""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageOps, ImageStat

CM = 2.54
TOLERANCE = 0.04  # inch and cm of one line agree within 4% (sellers round both)
VARIATION_MAX = 20  # Etsy's limit for a variation option name


# --- labels ---------------------------------------------------------------------------------------

def fmt_in(value: float) -> str:
    return f"{round(value, 1):g}"


def variation(w: float, h: float | None) -> str:
    """Etsy variation option, written solid (no spaces): 19.7"x12.9"/50x33cm. A long one (a square piece
    over a metre) drops its first inch mark, then the cm, so it always fits Etsy's 20 characters."""
    wi, wc = fmt_in(w), f"{w * CM:.0f}"
    if h is None:
        return f'{wi}"/{wc}cm'
    hi, hc = fmt_in(h), f"{h * CM:.0f}"
    for text in (f'{wi}"x{hi}"/{wc}x{hc}cm', f'{wi}x{hi}"/{wc}x{hc}cm'):
        if len(text) <= VARIATION_MAX:
            return text
    return f'{wi}"x{hi}"'


def dims(width_in: float, aspect: float | None) -> dict:
    """One size in both units. aspect = height / width of the design (None before the cut check).
    cm are derived from the inches shown, so the two always agree."""
    w = round(width_in, 1)
    out = {"w_in": width_in, "label_w": f'{fmt_in(w)}"'}
    if aspect:
        h = round(width_in * aspect, 1)
        out.update(h_in=h, label_in=f"{fmt_in(w)} × {fmt_in(h)} in", label_cm=f"{w * CM:.0f} × {h * CM:.0f} cm",
                   variation=variation(w, h))
    else:
        out.update(h_in=None, label_in=f"{fmt_in(w)} in wide", label_cm=f"{w * CM:.0f} cm wide",
                   variation=variation(w, None))
    return out


# --- reading size lists ---------------------------------------------------------------------------

_PRICE = re.compile(r"\([^)]*(?:US|\$|€|£|TL|EUR)[^)]*\)?"  # "(US$132.00)", even when OCR garbles the digits
                    r"|(?:US\s*|USD\s*|CA\s*|AU\s*)?[$€£]\s*[\w.,]+|[\dOo.,]+\s*(?:TL|USD|EUR)\b", re.I)
_NUM = r"(\d+(?:\.\d+)?)"
_CM_PART = re.compile(_NUM + r"\s*(?:x\s*" + _NUM + r"\s*)?cm\b", re.I)
_IN_MARKED = re.compile(_NUM + r"\s*(?:\"|'|in\b|inch(?:es)?\b)", re.I)
_IN_PAIR = re.compile(_NUM + r"\s*(?:\"|'|in\b)?\s*x\s*" + _NUM, re.I)  # "30"x13"", "30 x 13 in": width first
_BARE = re.compile(r"^\s*" + _NUM + r"\s*(?:x\s*" + _NUM + r")?\s*$")  # the whole line is just "30" or "30x13"


def _normalize(line: str) -> str:
    s = _PRICE.sub(" ", line)
    s = re.sub(r"[×X*]", "x", s)
    s = re.sub(r"[”“″‟〃°]|''", '"', s)  # OCR often reads the inch mark as a degree sign
    s = re.sub(r"[’‘`´]", "'", s)
    return re.sub(r"(\d),(\d)", r"\1.\2", s)


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= TOLERANCE * max(a, b)


def parse_line(line: str) -> dict | None:
    """One line of a size list -> {"w_in", "text", "note"} or None when it holds no size.
    Takes only the width (our height comes from the design); a cm reading glued to OCR noise
    ("137105x47cm" for "18"/105x47cm") is repaired from the inches on the same line."""
    s = _normalize(line)
    cm = _CM_PART.search(s)
    rest = s[:cm.start()] + " " + s[cm.end():] if cm else s
    first = _IN_PAIR.search(rest) or _IN_MARKED.search(rest)
    w_in = float(first.group(1)) if first else None
    if w_in is None and not cm:
        bare = _BARE.match(rest)  # a line that is only "30" or "30x13": inches (US listings)
        w_in = float(bare.group(1)) if bare else None
    note = ""
    if cm:
        digits = cm.group(1)
        w_cm = float(digits)
        if w_in is None:
            w_in = round(w_cm / CM, 2)
        elif not _close(w_in * CM, w_cm):
            # OCR mangled a mark: another number on the line may be the width the cm agree with,
            # or the cm digits carry noise in front ("137105" for "18"/105")
            other = next((float(n) for n in re.findall(_NUM, rest) if _close(float(n) * CM, w_cm)), None)
            fixed = next((float(digits[-k:]) for k in (3, 2) if len(digits) > k and _close(w_in * CM, float(digits[-k:]))), None)
            if other:
                w_in = other
            elif fixed:
                note = "cm okuması inçten düzeltildi"
            else:
                note = f"inç ({w_in:g}) ile cm ({w_cm:g}) tutmuyor — kontrol et"
    if w_in is None or not 1 <= w_in <= 200:
        return None
    return {"w_in": w_in, "text": line.strip(), "note": note}


def parse_text(text: str) -> list[dict]:
    """Every size found in a pasted list or OCR text, smallest first, one row per width."""
    rows: dict[float, dict] = {}
    for line in (text or "").splitlines():
        row = parse_line(line)
        if row and (row["w_in"] not in rows or not row["note"]):
            rows[row["w_in"]] = row
    return [rows[k] for k in sorted(rows)]


# --- OCR (Tesseract) ------------------------------------------------------------------------------

class OcrError(RuntimeError):
    """User-facing (Turkish) OCR problem."""


def tesseract() -> str | None:
    candidates = (
        os.environ.get("TESSERACT_EXE", ""),
        shutil.which("tesseract") or "",
        os.path.expandvars(r"%ProgramFiles%\Tesseract-OCR\tesseract.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
        "/opt/homebrew/bin/tesseract",  # Homebrew on Apple silicon
        "/usr/local/bin/tesseract",     # Homebrew on Intel Macs
    )
    return next((p for p in candidates if p and Path(p).is_file()), None)


def install_hint() -> str:
    if sys.platform == "darwin":
        return "Terminal'de 'brew install tesseract'"
    if os.name == "nt":
        return "PowerShell'de 'winget install --id UB-Mannheim.TesseractOCR'"
    return "'sudo apt install tesseract-ocr'"


def _prepare(image_bytes: bytes) -> Image.Image:
    """Screenshot -> large, high-contrast, dark-on-light grayscale (what Tesseract reads best)."""
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("L")
    except Exception as exc:  # PIL raises many types for bad files
        raise OcrError(f"Görsel açılamadı: {exc}") from exc
    if ImageStat.Stat(img).mean[0] < 128:  # dark mode
        img = ImageOps.invert(img)
    scale = max(1, min(4, round(1800 / max(img.width, 1))))
    img = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)
    return ImageOps.expand(ImageOps.autocontrast(img), 30, fill=255)


def ocr_text(image_bytes: bytes) -> str:
    exe = tesseract()
    if not exe:
        raise OcrError(f"Tesseract kurulu değil. Kurulum: {install_hint()} (ya da metni kutuya yapıştır).")
    img = _prepare(image_bytes)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "boylar.png"
        img.save(path)
        run = subprocess.run(
            [exe, str(path), "stdout", "--psm", "6", "-l", "eng"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    if run.returncode != 0:
        raise OcrError(f"Tesseract okuyamadı: {(run.stderr or '').strip()[:200]}")
    return run.stdout
