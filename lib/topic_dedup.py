from __future__ import annotations

import hashlib
import json
import re
from typing import Any

_SIGNATURE_FIELDS = (
    "ticker",
    "name",
    "headline",
    "catalyst",
    "thesis",
    "source",
    "overall_label",
    "title",
    "description",
    "text",
)


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).lower().strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^a-z0-9.%+\- ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def topic_fingerprint(item: dict[str, Any]) -> str:
    """Stable identity for a story topic, not the generated script output."""
    payload: dict[str, str] = {}
    for field in _SIGNATURE_FIELDS:
        value = _normalize_text(item.get(field))
        if value:
            payload[field] = value

    if not payload:
        dialogue = item.get("dialogue") or []
        if dialogue:
            joined = " | ".join(_normalize_text(line.get("text")) for line in dialogue if line.get("text"))
            if joined:
                payload["dialogue"] = joined

    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def dedupe_items(items: list[dict[str, Any]], blocked_keys: set[str]) -> list[dict[str, Any]]:
    """Drop items whose topic fingerprint is already blocked."""
    out: list[dict[str, Any]] = []
    seen = set(blocked_keys)
    for item in items:
        key = topic_fingerprint(item)
        if key in seen:
            continue
        seen.add(key)
        out.append({**item, "topic_key": key})
    return out
