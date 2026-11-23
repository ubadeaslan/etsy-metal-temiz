"""OpenAI REST: image generation, JSON text, model list."""
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

API = "https://api.openai.com/v1"
SIZES = {"1:1": "1024x1024", "3:2": "1536x1024", "2:3": "1024x1536"}


def _headers() -> dict:
    key = config.get_key("openai")
    if not key:
        raise ProviderError("OpenAI API anahtarı yok — Ayarlar sayfasından ekle.")
    return {"Authorization": f"Bearer {key}"}


def _error(resp: httpx.Response) -> ProviderError:
    try:
        message = resp.json().get("error", {}).get("message", resp.text)
    except ValueError:
        message = resp.text
    return ProviderError(f"OpenAI {resp.status_code}: {message[:400]}")


def generate_images(prompt: str, model: str, n: int, aspect: str, quality: str) -> list[bytes]:
    body = {"model": model, "prompt": prompt, "n": n, "size": SIZES.get(aspect, "1024x1024"), "quality": quality}
    with httpx.Client(timeout=300) as client:
        resp = _post(client, f"{API}/images/generations", headers=_headers(), json=body)
        if resp.status_code == 400:
            # Newer/older image models accept different size/quality values: retry with the bare minimum.
            resp = _post(client, f"{API}/images/generations", headers=_headers(),
                               json={"model": model, "prompt": prompt, "n": n})
        if resp.status_code != 200:
            raise _error(resp)
        images = []
        for item in resp.json().get("data", []):
            if item.get("b64_json"):
                images.append(base64.b64decode(item["b64_json"]))
            elif item.get("url"):
                images.append(client.get(item["url"]).content)
    if not images:
        raise ProviderError("OpenAI görsel döndürmedi (içerik filtresi olabilir — tarifi değiştir).")
    return images


def generate_json(system: str, user: str, model: str, image_png: bytes | None = None) -> dict:
    content: list[dict] = [{"type": "text", "text": user}]
    if image_png:
        data = base64.b64encode(image_png).decode()
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}})
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
        "response_format": {"type": "json_object"},
    }
    if model.startswith(("gpt-5", "o")):
        body["reasoning_effort"] = "low"  # listing text needs little reasoning; cuts latency a lot
    with httpx.Client(timeout=180) as client:
        resp = _post(client, f"{API}/chat/completions", headers=_headers(), json=body)
        if resp.status_code == 400 and "reasoning_effort" in body:
            body.pop("reasoning_effort")
            resp = _post(client, f"{API}/chat/completions", headers=_headers(), json=body)
    if resp.status_code != 200:
        raise _error(resp)
    text = resp.json()["choices"][0]["message"]["content"]
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProviderError(f"OpenAI geçerli JSON döndürmedi: {exc}") from exc


def list_models() -> dict:
    with httpx.Client(timeout=30) as client:
        resp = client.get(f"{API}/models", headers=_headers())
    if resp.status_code != 200:
        raise _error(resp)
    ids = sorted(m["id"] for m in resp.json().get("data", []))
    skip = ("audio", "realtime", "tts", "transcribe", "embedding", "search", "moderation", "whisper", "davinci", "babbage")
    image = [i for i in ids if "image" in i or i.startswith("dall-e")]
    text = [i for i in ids if (i.startswith("gpt-") or i.startswith("o")) and i not in image and not any(s in i for s in skip)]
    return {"image": image, "text": text}
