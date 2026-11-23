"""Gemini REST (generativelanguage v1beta): image generation, JSON text, model list."""
from __future__ import annotations

import base64
import json
import time

import httpx

from .. import config
from .errors import ProviderError


RETRY_STATUS = (500, 502, 503, 504)


def _post(client: httpx.Client, url: str, **kwargs) -> httpx.Response:
    """POST with two short retries on transient server errors (overload, gateway)."""
    for wait in (2, 6, None):
        resp = client.post(url, **kwargs)
        if resp.status_code not in RETRY_STATUS or wait is None:
            return resp
        time.sleep(wait)
    return resp

API = "https://generativelanguage.googleapis.com/v1beta"


def _headers() -> dict:
    key = config.get_key("gemini")
    if not key:
        raise ProviderError("Gemini API anahtarı yok — Ayarlar sayfasından ekle.")
    return {"x-goog-api-key": key}


def _error(resp: httpx.Response) -> ProviderError:
    try:
        message = resp.json().get("error", {}).get("message", resp.text)
    except ValueError:
        message = resp.text
    hint = ""
    if resp.status_code == 429 and "free_tier" in message:
        hint = ("Gemini anahtarın ÜCRETSİZ katmanda; görsel modellerin ücretsiz kotası 0. "
                "Google AI Studio → Billing'den faturalandırmayı aç ya da görselde OpenAI'yi seç. — ")
    elif resp.status_code == 503:
        hint = "Gemini şu an yoğun (geçici). Biraz sonra tekrar dene ya da OpenAI'yi seç. — "
    return ProviderError(f"{hint}Gemini {resp.status_code}: {message[:300]}")


def _model_path(model: str) -> str:
    return model if model.startswith("models/") else f"models/{model}"


def _parts(resp_json: dict) -> list[dict]:
    feedback = resp_json.get("promptFeedback", {})
    if feedback.get("blockReason"):
        raise ProviderError(f"Gemini isteği engelledi ({feedback['blockReason']}) — tarifi değiştir.")
    candidates = resp_json.get("candidates") or []
    if not candidates:
        raise ProviderError("Gemini yanıt üretmedi.")
    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    if not parts:
        reason = candidates[0].get("finishReason", "?")
        raise ProviderError(f"Gemini boş yanıt döndürdü (finishReason={reason}) — tarifi değiştir.")
    return parts


def generate_image(prompt: str, model: str, aspect: str, image_png: bytes | None = None) -> bytes:
    parts: list[dict] = [{"text": prompt}]
    if image_png:
        parts.append({"inlineData": {"mimeType": "image/png", "data": base64.b64encode(image_png).decode()}})
    attempts = [
        {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": aspect}},
        {"responseModalities": ["TEXT", "IMAGE"]},
    ]
    url = f"{API}/{_model_path(model)}:generateContent"
    with httpx.Client(timeout=300) as client:
        for i, gen_config in enumerate(attempts):
            resp = _post(client, url, headers=_headers(),
                               json={"contents": [{"parts": parts}], "generationConfig": gen_config})
            if resp.status_code == 400 and i + 1 < len(attempts):
                continue  # model rejected the config shape: retry with the older one
            if resp.status_code != 200:
                raise _error(resp)
            for part in _parts(resp.json()):
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    return base64.b64decode(inline["data"])
            raise ProviderError("Gemini görsel yerine yalnız metin döndürdü — tarifi değiştir ya da görsel modeli seç.")
    raise ProviderError("Gemini görsel üretemedi.")


def generate_json(system: str, user: str, model: str, image_png: bytes | None = None) -> dict:
    parts: list[dict] = [{"text": user}]
    if image_png:
        parts.append({"inlineData": {"mimeType": "image/png", "data": base64.b64encode(image_png).decode()}})
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    with httpx.Client(timeout=180) as client:
        resp = _post(client, f"{API}/{_model_path(model)}:generateContent", headers=_headers(), json=body)
    if resp.status_code != 200:
        raise _error(resp)
    text = "".join(p.get("text", "") for p in _parts(resp.json()))
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProviderError(f"Gemini geçerli JSON döndürmedi: {exc}") from exc


def list_models() -> dict:
    with httpx.Client(timeout=30) as client:
        resp = client.get(f"{API}/models", headers=_headers(), params={"pageSize": 1000})
    if resp.status_code != 200:
        raise _error(resp)
    image, text = [], []
    for m in resp.json().get("models", []):
        if "generateContent" not in m.get("supportedGenerationMethods", []):
            continue
        name = m["name"].removeprefix("models/")
        if any(s in name for s in ("embedding", "aqa", "tts", "audio", "live")):
            continue
        (image if "image" in name else text).append(name)
    return {"image": sorted(image), "text": sorted(text)}
