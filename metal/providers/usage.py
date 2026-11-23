"""Spend ledger (calisma/harcama.jsonl) and the monthly budget gate.

Costs are estimates: the provider console is the real meter.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime

from .. import config

_lock = threading.Lock()


class BudgetError(RuntimeError):
    pass


def _entries():
    if not config.USAGE_FILE.exists():
        return []
    rows = []
    for line in config.USAGE_FILE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def month_total(month: str | None = None) -> float:
    month = month or datetime.now().strftime("%Y-%m")
    return round(sum(r.get("cost_usd", 0.0) for r in _entries() if r.get("at", "").startswith(month)), 4)


def month_breakdown(month: str | None = None) -> dict:
    month = month or datetime.now().strftime("%Y-%m")
    out: dict[str, dict] = {}
    for row in _entries():
        if not row.get("at", "").startswith(month):
            continue
        key = f"{row['provider']} · {row['kind']}"
        slot = out.setdefault(key, {"calls": 0, "cost_usd": 0.0})
        slot["calls"] += 1
        slot["cost_usd"] = round(slot["cost_usd"] + row.get("cost_usd", 0.0), 4)
    return out


def check(estimate: float) -> None:
    budget = float(config.load_settings()["monthly_budget_usd"])
    spent = month_total()
    if spent + estimate > budget:
        raise BudgetError(
            f"Aylık AI bütçesi aşılır: bu ay ~${spent:.2f} harcandı, bu çağrı ~${estimate:.2f}, "
            f"tavan ${budget:.2f}. Ayarlar'dan tavanı yükseltebilirsin."
        )


def record(provider: str, model: str, kind: str, cost: float, design_id: str | None = None, **meta) -> None:
    row = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "provider": provider,
        "model": model,
        "kind": kind,
        "cost_usd": round(cost, 4),
        "design": design_id,
        **meta,
    }
    config.WORK.mkdir(parents=True, exist_ok=True)
    with _lock, config.USAGE_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def image_estimate(provider: str, n: int) -> float:
    est = config.load_settings()["cost_estimates"]
    if provider == "openai":
        quality = config.load_settings().get("openai_image_quality", "medium")
        return est["openai_image"].get(quality, 0.07) * n
    return est["gemini_image"] * n


def text_estimate() -> float:
    return float(config.load_settings()["cost_estimates"]["text_call"])
