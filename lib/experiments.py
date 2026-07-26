import hashlib
import re
from statistics import mean
from typing import Any


EXPERIMENT_ID = "shorts-discovery-v1"
EXPERIMENT_PLAN = (
    "baseline_dialogue",
    "move_mechanism",
    "baseline_dialogue",
    "catalyst_checkpoint",
    "baseline_dialogue",
    "radar_invalidation",
)
MIN_PUBLISH_INTERVAL_HOURS = 48

_FORMAT_PROMPTS = {
    "baseline_dialogue": "",
    "move_mechanism": (
        "Open with the exact company and percentage move, then the contradiction. "
        "Explain one mechanism behind the move and one concrete number proving it. "
        "Use one sentence and one causal claim per turn. End with one checkpoint. "
        "Title the exact move or mechanism. "
        "Never say buy, sell, or hold."
    ),
    "catalyst_checkpoint": (
        "Open with the exact company and percentage move, then the catalyst. "
        "Use one concrete number as proof. Use one sentence and one causal claim per "
        "turn, then end "
        "with the next dated or measurable checkpoint. Title the catalyst, not a "
        "generic question. Never say buy, sell, or hold."
    ),
    "radar_invalidation": (
        "Open with the exact company and percentage move, then the market's apparent "
        "belief. Use one concrete number as proof and identify the single fact that "
        "would invalidate that belief. Use one sentence and one causal claim per "
        "turn. Title the contradiction or invalidation. "
        "Never say buy, sell, or hold."
    ),
}

_VAGUE_PHRASES = (
    "market silence",
    "no clear catalyst",
    "no catalyst",
    "investors are watching",
    "traders are watching",
    "the market is watching",
    "sentiment",
)
_SPECIFIC_TERMS = re.compile(
    r"\b(earnings|revenue|sales|margin|guidance|forecast|orders?|contract|"
    r"launch|approval|capex|cash flow|profit|loss|eps|ebitda|delivery|"
    r"shipments?|backlog|rate cut|tariff|acquisition|merger)\b",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"(?:[$€£]\s*)?\d+(?:\.\d+)?\s*(?:%|billion|million|bn|m)?", re.I)


def assignment_id(experiment_id: str, slot: int, topic_key: str) -> str:
    raw = f"{experiment_id}:{slot}:{topic_key}".encode()
    return hashlib.sha256(raw).hexdigest()[:24]


def format_prompt(variant: str) -> str:
    return _FORMAT_PROMPTS[variant]


def format_settings(variant: str) -> dict[str, Any]:
    if variant == "baseline_dialogue":
        return {}
    if variant not in _FORMAT_PROMPTS:
        raise ValueError(f"Unknown experiment variant: {variant}")
    settings = {
        "speaker_scale": 0.30,
        "subtitle_margin": 180,
        "subtitle_fontsize": 74,
    }
    if variant == "catalyst_checkpoint":
        settings.update({"speaker_scale": 0.28, "speaker_corner": "bottom-left"})
    elif variant == "radar_invalidation":
        settings["speaker_scale"] = 0.26
    return settings


def _short_text(value: Any, limit: int = 76) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else f"{text[: limit - 1].rstrip()}…"


def build_components(pick: dict[str, Any], variant: str) -> list[dict[str, Any]]:
    if variant == "baseline_dialogue":
        return []
    if variant not in _FORMAT_PROMPTS:
        raise ValueError(f"Unknown experiment variant: {variant}")

    ticker = str(pick.get("ticker") or "").upper()
    company = _short_text(pick.get("company") or pick.get("name") or ticker, 30)
    move = float(
        pick.get("move_pct")
        or pick.get("change_pct")
        or pick.get("pct_change")
        or 0
    )
    catalyst = (
        pick.get("catalyst")
        or pick.get("headline")
        or "Price move needs confirmation"
    )
    thesis = (
        pick.get("thesis")
        or pick.get("headline")
        or "The market is repricing one assumption"
    )
    checkpoint = (
        pick.get("watch")
        or pick.get("checkpoint")
        or pick.get("thesis")
        or "Watch whether the move holds"
    )
    first_line = str(((pick.get("dialogue") or [{}])[0]).get("text") or "")
    match = re.search(r"\b(despite|but|yet|although|while)\b.+", first_line, re.I)
    contradiction = match.group(0) if match else pick.get("headline") or thesis
    first = {
        "type": "big_move",
        "show_at": 0,
        "data": {
            "name": f"{company} ({ticker})",
            "pct": move,
            "contradiction": _short_text(contradiction, 68),
        },
    }
    if variant == "move_mechanism":
        return [
            first,
            {
                "type": "context_quote",
                "show_at": 0.20,
                "data": {"source": "MECHANISM", "text": _short_text(catalyst)},
            },
            {
                "type": "context_quote",
                "show_at": 0.48,
                "data": {"source": "PROOF TO WATCH", "text": _short_text(checkpoint)},
            },
        ]
    if variant == "catalyst_checkpoint":
        return [
            first,
            {
                "type": "company_card",
                "show_at": 0.20,
                "data": {"name": company, "sector": _short_text(pick.get("sector"), 28)},
            },
            {
                "type": "context_quote",
                "show_at": 0.42,
                "data": {"source": "CATALYST", "text": _short_text(catalyst)},
            },
            {
                "type": "context_quote",
                "show_at": 0.66,
                "data": {"source": "NEXT CHECKPOINT", "text": _short_text(checkpoint)},
            },
        ]
    return [
        first,
        {
            "type": "context_quote",
            "show_at": 0.20,
            "data": {"source": "MARKET BELIEF", "text": _short_text(thesis)},
        },
        {
            "type": "context_quote",
            "show_at": 0.48,
            "data": {
                "source": "INVALIDATED IF",
                "text": _short_text(pick.get("invalidation") or catalyst),
            },
        },
    ]


def story_score(pick: dict[str, Any]) -> float:
    move = abs(
        float(
            pick.get("move_pct")
            or pick.get("change_pct")
            or pick.get("pct_change")
            or 0
        )
    )
    text = " ".join(
        str(pick.get(key) or "")
        for key in ("headline", "catalyst", "thesis", "context", "reason")
    )
    score = min(move, 25.0)
    score += min(len(_NUMBER.findall(text)), 3) * 2.0
    score += min(len(_SPECIFIC_TERMS.findall(text)), 3) * 2.0
    lowered = text.lower()
    score -= sum(3.0 for phrase in _VAGUE_PHRASES if phrase in lowered)
    return score


def rank_story_picks(
    picks: list[dict[str, Any]], min_move_pct: float = 5
) -> list[dict[str, Any]]:
    ranked = []
    for pick in picks:
        move = abs(
            float(
                pick.get("move_pct")
                or pick.get("change_pct")
                or pick.get("pct_change")
                or 0
            )
        )
        if move >= min_move_pct:
            ranked.append({**pick, "selection_score": story_score(pick)})
    return sorted(ranked, key=lambda item: item["selection_score"], reverse=True)


def validate_buffer_results(
    results: list[dict[str, Any]], required_services: tuple[str, ...] = ("youtube", "instagram")
) -> None:
    """Require Buffer acceptance for every requested channel; not platform publication."""
    required = {service.lower() for service in required_services}
    present = {str(item.get("service", "")).lower() for item in results}
    failures = sorted(required - present)
    failures.extend(
        str(item.get("service") or "unknown")
        for item in results
        if str(item.get("service", "")).lower() in required
        and str(item.get("status", "")).lower() not in {"posted", "scheduled"}
    )
    if failures:
        raise RuntimeError(f"Publishing not confirmed for: {', '.join(failures)}")


def _group_metrics(rows: list[dict[str, Any]]) -> dict[str, float]:
    fields = (
        "shown_in_feed",
        "stayed_to_watch_pct",
        "swiped_away_pct",
        "avg_view_duration_seconds",
        "avg_percentage_viewed",
        "shorts_feed_share_pct",
        "views",
        "subscriber_change",
    )
    metrics = {
        field: mean(float(row[field]) for row in rows if row.get(field) not in (None, ""))
        for field in fields
        if any(row.get(field) not in (None, "") for row in rows)
    }
    metrics["videos"] = len(rows)
    return metrics


def summarize_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    experiment_ids = {row.get("experiment_id") for row in rows}
    if experiment_ids != {EXPERIMENT_ID}:
        return {"gate": "invalid_experiment_ids", "experiment_ids": sorted(map(str, experiment_ids))}
    assignment_ids = [row.get("assignment_id") for row in rows]
    try:
        slots = {int(row["slot"]) for row in rows}
        plan_matches = all(
            0 <= int(row["slot"]) < len(EXPERIMENT_PLAN)
            and row.get("variant") == EXPERIMENT_PLAN[int(row["slot"])]
            for row in rows
        )
    except (KeyError, TypeError, ValueError):
        slots = set()
        plan_matches = False
    if (
        len(rows) != 6
        or len(set(assignment_ids)) != 6
        or None in assignment_ids
        or slots != set(range(6))
        or not plan_matches
    ):
        return {"gate": "incomplete_experiment"}

    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row.get("variant") or "unknown"), []).append(row)
    summary = {variant: _group_metrics(items) for variant, items in groups.items()}

    baseline = summary.get("baseline_dialogue")
    if not baseline:
        return {"variants": summary, "gate": "insufficient_baseline"}

    new_rows = [row for row in rows if row.get("variant") != "baseline_dialogue"]
    new_formats = _group_metrics(new_rows) if new_rows else {}
    expected_new = set(EXPERIMENT_PLAN) - {"baseline_dialogue"}
    complete = (
        baseline["videos"] == 3
        and new_formats.get("videos") == 3
        and expected_new <= set(groups)
    )
    if not complete:
        return {
            "variants": summary,
            "gate": "incomplete_experiment",
            "baseline": baseline,
            "new_formats": new_formats,
            "new_format_passes_retention_gate": False,
        }
    required = {"stayed_to_watch_pct", "avg_percentage_viewed"}
    enough_data = required <= baseline.keys() and required <= new_formats.keys()
    passed = enough_data and (
        new_formats["stayed_to_watch_pct"] >= baseline["stayed_to_watch_pct"] + 5
        and new_formats["avg_percentage_viewed"]
        >= baseline["avg_percentage_viewed"] - 5
    )
    return {
        "variants": summary,
        "gate": "pass" if passed else "fail" if enough_data else "insufficient_metrics",
        "baseline": baseline,
        "new_formats": new_formats,
        "new_format_passes_retention_gate": passed,
    }
