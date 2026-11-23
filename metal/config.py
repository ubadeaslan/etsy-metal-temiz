"""Paths, settings (calisma/ayarlar.json) and API keys (.env).

Everything that belongs to the person using the panel (designs, rooms, cards, settings, spend) lives in
calisma/, the keys in .env. Neither is in git: the program ships empty and each install keeps its own."""
from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "calisma"
DESIGNS = WORK / "tasarimlar"
ROOMS = WORK / "arka-planlar"
SETTINGS_FILE = WORK / "ayarlar.json"
USAGE_FILE = WORK / "harcama.jsonl"
ENV_FILE = ROOT / ".env"
ASSETS = Path(__file__).resolve().parent / "assets"
FONTS = ASSETS / "fonts"
READY_CARDS = WORK / "kartlar"  # the shop's own finished images (Ayarlar), added to its listings

KEY_NAMES = {"openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY"}

DEFAULTS: dict = {
    "image_provider": "gemini",
    "text_provider": "gemini",
    "models": {
        "openai": {"image": "gpt-image-2", "text": "gpt-5-mini"},
        "gemini": {"image": "gemini-3.1-flash-image", "text": "gemini-3.5-flash"},
    },
    "openai_image_quality": "medium",
    "monthly_budget_usd": 20.0,
    # Rough per-call estimates (USD) used when the API returns no usable token counts.
    # They are deliberately on the high side; the provider console is the real meter.
    "cost_estimates": {
        "openai_image": {"low": 0.02, "medium": 0.07, "high": 0.25},
        "gemini_image": 0.08,
        "text_call": 0.01,
    },
    "cut": {
        "thickness_mm": 1.5,
        "min_width_mm": 3.0,
        "min_hole_mm": 4.0,
        "min_gap_mm": 2.0,
        "speck_mm2": 2.0,
        "clock_hub_frac": 0.12,
        "clock_hole_mm": 10.0,
    },
    "sizes_in": [16, 20, 24, 30, 36],  # widths a new design starts with; every design keeps its own list
    # SKU = prefix + number; a new design takes the lowest free number, so a deleted design's SKU becomes
    # free again.
    "sku_prefix": "SKU-",
    "sku_start": 1001,
    # The shop as the listing description signs off (empty = a plain thank-you without a name).
    "shop": {"name": "", "slogan": "", "story": ""},
    # A listing description whose tone the text model follows (empty = the neutral one in listing.py).
    "style_example": "",
    # Product facts used by the listing text and the info card. Empty = never mentioned: what the piece is
    # made of, how it ships and how it is cared for differ from shop to shop.
    "facts": {
        "material": "",
        "thickness_mm": 1.5,
        "coating": "",
        "mounting": "",
        "clock_movement": "",
        "clock_hands_included": False,
        "personalization": "Enter the name or text you want in the personalization box.",
        "processing_time": "",
        "ships_from": "",
        "indoor_outdoor": "",
        "care": "",
    },
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return _merge(DEFAULTS, json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
    return copy.deepcopy(DEFAULTS)


def parse_sizes(values: list[str], extra: str = "") -> list[float]:
    """Ticked size chips + a typed list ("40, 44") -> sorted unique widths in inches (whole numbers as int)."""
    out: set[float] = set()
    for raw in [*values, *re.split(r"[,;\s]+", extra or "")]:
        try:
            value = float(str(raw).strip())
        except ValueError:
            continue
        if 1 <= value <= 200:
            out.add(int(value) if value.is_integer() else round(value, 2))
    return sorted(out)


def save_settings(settings: dict) -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def load_keys() -> None:
    load_dotenv(ENV_FILE, override=True)


def get_key(provider: str) -> str:
    load_keys()
    return os.environ.get(KEY_NAMES[provider], "").strip()


def set_key(provider: str, value: str) -> None:
    """Write one key into .env, keeping the other lines."""
    name = KEY_NAMES[provider]
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    lines = [line for line in lines if not line.startswith(f"{name}=")]
    lines.append(f"{name}={value.strip()}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[name] = value.strip()


def masked_key(provider: str) -> str:
    key = get_key(provider)
    if not key:
        return ""
    return key[:4] + "…" + key[-4:] if len(key) > 10 else "••••"
