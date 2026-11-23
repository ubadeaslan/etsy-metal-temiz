"""Room photos for mockups: user's own photos or AI-generated empty walls (calisma/arka-planlar/)."""
from __future__ import annotations

import io
import json
import secrets
import shutil
from datetime import datetime

from PIL import Image

from . import config

REGISTRY = "odalar.json"
DEFAULT_BOX = [0.25, 0.05, 0.75, 0.51]  # upper-middle wall

ROOM_PRESETS = {
    "salon": "a bright modern living room with a light sofa against the wall",
    "yatak": "a calm bedroom with an upholstered bed headboard against the wall",
    "giris": "an entryway with a slim wooden console table against the wall",
    "ofis": "a home office with a wooden desk against the wall",
    "yemek": "a dining area with a wooden table and chairs in front of the wall",
    "dis-mekan": "a covered patio with a stucco exterior wall and outdoor chairs",
}


def room_prompt(preset: str, wall_note: str = "") -> str:
    scene = ROOM_PRESETS.get(preset, preset)
    return (
        f"Photorealistic interior photograph of {scene}. Straight-on frontal view, camera at eye level, "
        "level horizon, no perspective tilt. The upper middle of the wall is a large EMPTY, evenly lit, "
        f"plain painted wall area {wall_note or 'in a warm neutral color'} with nothing on it: no art, no frames, "
        "no shelves, no lamps, no plants on the wall. Soft natural daylight, realistic shadows, high detail, "
        "Square 1:1 format. No people, no text, no logos."
    )


def _registry() -> dict:
    path = config.ROOMS / REGISTRY
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"rooms": []}


def _save(reg: dict) -> None:
    config.ROOMS.mkdir(parents=True, exist_ok=True)
    (config.ROOMS / REGISTRY).write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")


def list_rooms() -> list[dict]:
    return _registry()["rooms"]


def get(room_id: str) -> dict | None:
    return next((r for r in list_rooms() if r["id"] == room_id), None)


def add(image_bytes: bytes, source: str, name: str, prompt: str = "", provider: str = "", model: str = "") -> dict:
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    room_id = f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
    config.ROOMS.mkdir(parents=True, exist_ok=True)
    file = f"{room_id}.jpg"
    img.save(config.ROOMS / file, "JPEG", quality=92)
    room = {
        "id": room_id, "file": file, "name": name or room_id, "source": source,
        "box": list(DEFAULT_BOX), "prompt": prompt, "provider": provider, "model": model,
        "created": datetime.now().isoformat(timespec="seconds"), "size": list(img.size),
    }
    reg = _registry()
    reg["rooms"].append(room)
    _save(reg)
    return room


def missing_starters() -> list[str]:
    """The program's own rooms that this install's library does not have (never added, or deleted)."""
    have = {r["id"] for r in list_rooms()}
    return [p.stem for p in sorted(config.STARTER_ROOMS.glob("*.jpg")) if p.stem not in have]


def add_starters() -> int:
    """Copy the program's rooms (AI-drawn empty walls) into this install's own library, where they can be
    moved, reset or deleted like any other room."""
    names = missing_starters()
    if not names:
        return 0
    config.ROOMS.mkdir(parents=True, exist_ok=True)
    reg = _registry()
    for name in names:
        shutil.copyfile(config.STARTER_ROOMS / f"{name}.jpg", config.ROOMS / f"{name}.jpg")
        with Image.open(config.ROOMS / f"{name}.jpg") as img:
            size = list(img.size)
        reg["rooms"].append({
            "id": name, "file": f"{name}.jpg", "name": name, "source": "ai", "box": list(DEFAULT_BOX),
            "prompt": "", "provider": "", "model": "", "created": datetime.now().isoformat(timespec="seconds"), "size": size,
        })
    _save(reg)
    return len(names)


def first_run() -> None:
    """A fresh install starts with the program's rooms; a library that exists, even emptied, is left alone."""
    if not (config.ROOMS / REGISTRY).exists():
        add_starters()


def set_box(room_id: str, box: list[float]) -> None:
    x0, y0, x1, y1 = (min(max(float(v), 0.0), 1.0) for v in box)
    if x1 - x0 < 0.05 or y1 - y0 < 0.05:
        raise ValueError("yerleşim kutusu çok küçük")
    reg = _registry()
    for room in reg["rooms"]:
        if room["id"] == room_id:
            room["box"] = [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)]
    _save(reg)


def reset_box(room_id: str) -> list[float]:
    set_box(room_id, DEFAULT_BOX)
    return list(DEFAULT_BOX)


def delete(room_id: str) -> None:
    reg = _registry()
    room = next((r for r in reg["rooms"] if r["id"] == room_id), None)
    if room:
        (config.ROOMS / room["file"]).unlink(missing_ok=True)
        reg["rooms"] = [r for r in reg["rooms"] if r["id"] != room_id]
        _save(reg)
