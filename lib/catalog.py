"""Pick items from indexed catalogs (gameplay, speaker, etc.)."""
from __future__ import annotations

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(name: str) -> list[dict]:
    path = ROOT / "catalog" / f"{name}.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return data.get("items", [])


def resolve_path(item: dict) -> Path:
    rel = item.get("path")
    if not rel:
        raise ValueError(f"Catalog item missing path: {item}")
    p = ROOT / rel
    if not p.exists():
        raise FileNotFoundError(f"Asset not found: {p}")
    return p


def pick(name: str, *, tags: list[str] | None = None, item_id: str | None = None,
         mode: str = "random") -> dict:
    items = load(name)
    if tags:
        items = [it for it in items if any(t in it.get("tags", []) for t in tags)]
    if item_id:
        items = [it for it in items if it.get("id") == item_id]
    if not items:
        raise ValueError(f"No items in catalog '{name}' (tags={tags}, id={item_id})")
    if mode == "random":
        return random.choice(items)
    if mode == "first":
        return items[0]
    raise ValueError(f"Unknown pick mode: {mode}")
