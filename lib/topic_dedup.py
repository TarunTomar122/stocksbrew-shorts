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


_ANGLE_STOPWORDS = {
    "a",
    "after",
    "and",
    "at",
    "company",
    "for",
    "from",
    "in",
    "is",
    "its",
    "of",
    "on",
    "stock",
    "the",
    "to",
}


def _angle_terms(item: dict[str, Any]) -> set[str]:
    text = " ".join(
        _normalize_text(item.get(field))
        for field in ("ticker", "headline", "catalyst", "thesis")
    )
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text)
        if len(token) > 1 and token not in _ANGLE_STOPWORDS
    }


def is_near_duplicate(
    item: dict[str, Any],
    prior_items: list[dict[str, Any]],
    threshold: float = 0.35,
) -> bool:
    """Match repeated ticker angles while allowing a genuinely new catalyst."""
    ticker = _normalize_text(item.get("ticker"))
    terms = _angle_terms(item)
    if not ticker or not terms:
        return False
    for prior in prior_items:
        if _normalize_text(prior.get("ticker")) != ticker:
            continue
        prior_terms = _angle_terms(prior)
        union = terms | prior_terms
        if union and len(terms & prior_terms) / len(union) >= threshold:
            return True
    return False
