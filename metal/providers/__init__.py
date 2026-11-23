"""Provider facade: budget gate -> call -> ledger. The panel only talks to this module."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from .. import config
from . import gemini_p, openai_p, usage
from .errors import ProviderError
from .usage import BudgetError

PROVIDERS = {"openai": "OpenAI", "gemini": "Gemini"}

__all__ = ["PROVIDERS", "ProviderError", "BudgetError", "generate_images", "generate_json", "list_models", "model_for"]


def model_for(provider: str, kind: str) -> str:
    return config.load_settings()["models"][provider][kind]


def generate_images(provider: str, prompt: str, n: int, aspect: str, model: str | None = None,
                    design_id: str | None = None, image_png: bytes | None = None) -> tuple[list[bytes], dict]:
    """Returns (png/jpeg bytes per image, call info for the production record)."""
    if provider not in PROVIDERS:
        raise ProviderError(f"bilinmeyen sağlayıcı: {provider}")
    model = model or model_for(provider, "image")
    n = max(1, min(int(n), 6))
    estimate = usage.image_estimate(provider, n)
    usage.check(estimate)
    if provider == "openai":
        quality = config.load_settings().get("openai_image_quality", "medium")
        images = openai_p.generate_images(prompt, model, n, aspect, quality)
    else:
        with ThreadPoolExecutor(max_workers=n) as pool:
            futures = [pool.submit(gemini_p.generate_image, prompt, model, aspect, image_png) for _ in range(n)]
            images, errors = [], []
            for future in futures:
                try:
                    images.append(future.result())
                except ProviderError as exc:
                    errors.append(str(exc))
        if not images:
            raise ProviderError(errors[0] if errors else "Gemini görsel üretemedi.")
    cost = usage.image_estimate(provider, len(images))
    usage.record(provider, model, "image", cost, design_id, n=len(images))
    return images, {"provider": provider, "model": model, "cost_usd": round(cost, 4)}


def generate_json(provider: str, system: str, user: str, image_png: bytes | None = None,
                  model: str | None = None, design_id: str | None = None) -> tuple[dict, dict]:
    if provider not in PROVIDERS:
        raise ProviderError(f"bilinmeyen sağlayıcı: {provider}")
    model = model or model_for(provider, "text")
    estimate = usage.text_estimate()
    usage.check(estimate)
    module = openai_p if provider == "openai" else gemini_p
    data = module.generate_json(system, user, model, image_png)
    usage.record(provider, model, "text", estimate, design_id)
    return data, {"provider": provider, "model": model, "cost_usd": estimate}


def list_models(provider: str) -> dict:
    module = openai_p if provider == "openai" else gemini_p
    return module.list_models()
