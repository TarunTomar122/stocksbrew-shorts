"""Firestore admin client for reading stocksbrew market data.

Uses the service account JSON configured via FIREBASE_CREDENTIALS_PATH.
Read-only against the server-only collections (tm_heat_list, tm_latest_prices,
tm_market_movers, tm_premarket_movers, tm_news_runs).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

load_dotenv(ROOT / ".env")

_firebase_app = None
_firestore_client = None
SHORT_TOPIC_HISTORY_COLLECTION = "tm_short_topic_history"


def _ensure_app():
    global _firebase_app, _firestore_client
    if _firestore_client is not None:
        return _firestore_client

    import firebase_admin
    from firebase_admin import credentials, firestore

    if firebase_admin._apps:
        _firebase_app = firebase_admin.get_app()
    else:
        cred_path = os.environ.get(
            "FIREBASE_CREDENTIALS_PATH",
            str(ROOT / "firebase-credentials.json"),
        )
        if not Path(cred_path).exists():
            raise FileNotFoundError(
                f"Firebase credentials not found at {cred_path}. "
                "Set FIREBASE_CREDENTIALS_PATH or drop the JSON in repo root."
            )
        cred = credentials.Certificate(cred_path)
        _firebase_app = firebase_admin.initialize_app(cred)

    _firestore_client = firestore.client()
    return _firestore_client


def _doc_to_dict(doc) -> dict[str, Any]:
    return doc.to_dict() or {}


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return None


def get_heat_list(market: str = "US") -> dict[str, Any] | None:
    """Return the compact frontend view of today's heat list for `market`.

    Each row: {instrument_id, ticker, name, setup_type, heat_score, reasons,
    price_change_pct, rsi, ...}. Top rows are sorted by heat_score.
    """
    db = _ensure_app()
    doc = db.collection("tm_heat_list_view").document(market).get()
    return _doc_to_dict(doc) if doc.exists else None


def get_heat_list_rows(market: str = "US", min_score: float = 0.0) -> list[dict[str, Any]]:
    """Return just the rows from the heat list, filtered by min score."""
    payload = get_heat_list(market)
    if not payload:
        return []
    rows = payload.get("rows") or []
    return [r for r in rows if float(r.get("heat_score") or 0) >= min_score]


def get_latest_price(instrument_id: str) -> dict[str, Any] | None:
    """Latest quote for an instrument. Includes price.changePct, price.last, etc."""
    db = _ensure_app()
    doc = db.collection("tm_latest_prices").document(instrument_id).get()
    return _doc_to_dict(doc) if doc.exists else None


def get_market_movers(market: str = "US") -> dict[str, Any] | None:
    """Gainers + losers + active for the market."""
    db = _ensure_app()
    doc = db.collection("tm_market_movers").document(market).get()
    return _doc_to_dict(doc) if doc.exists else None


def get_premarket_movers(market: str = "US") -> dict[str, Any] | None:
    db = _ensure_app()
    doc = db.collection("tm_premarket_movers").document(f"{market}__latest").get()
    return _doc_to_dict(doc) if doc.exists else None


def get_ticker_intel(market: str, universe_id: str, instrument_id: str) -> dict[str, Any] | None:
    """Four-pillar scored intel doc from tm_stock_intel_pro."""
    db = _ensure_app()
    doc = (
        db.collection("tm_stock_intel_pro")
        .document(f"{market}__{universe_id}")
        .collection("stocks")
        .document(instrument_id)
        .get()
    )
    return _doc_to_dict(doc) if doc.exists else None


def get_active_universe(market: str = "US") -> str | None:
    db = _ensure_app()
    doc = db.collection("tm_config").document("active_universes").get()
    if not doc.exists:
        return None
    data = doc.to_dict() or {}
    key = "US_universe" if market.upper() == "US" else f"{market.upper()}_universe"
    return data.get(key)


def extract_ticker_from_instrument_id(instrument_id: str) -> str:
    """`US_NVDA` -> `NVDA`, `IN_RELIANCE` -> `RELIANCE`."""
    return instrument_id.split("_", 1)[-1] if "_" in instrument_id else instrument_id


def get_daily_anomalies(market: str = "US", limit: int = 10) -> list[dict[str, Any]]:
    """Return the latest daily anomaly picks — stocks with unusual moves + context.

    Each anomaly: {ticker, name, day_change_pct, headline, catalyst, thesis,
    sector, direction, overall_label, price, volume}. These are the best
    source for story-driven scripts because they already have a narrative.
    """
    db = _ensure_app()
    # Fetch without composite index — just get recent docs and sort client-side
    docs = list(db.collection("tm_daily_anomalies").limit(10).stream())
    best = None
    best_date = ""
    for doc in docs:
        data = _doc_to_dict(doc)
        if data.get("market", "").upper() != market.upper():
            continue
        d = str(data.get("date", ""))
        if d > best_date:
            best_date = d
            best = data
    if not best:
        return []
    anomalies = best.get("anomalies") or []
    anomalies.sort(
        key=lambda a: abs(float(a.get("day_change_pct") or 0)),
        reverse=True,
    )
    return anomalies[:limit]


def get_reddit_buzz(min_posts: int = 10, limit: int = 5) -> list[dict[str, Any]]:
    """Return tickers with notable Reddit discussion volume.

    Each result: {ticker, post_count, notable_discussions, top_posts (titles)}.
    """
    db = _ensure_app()
    docs = list(db.collection("reddit_ticker_contexts").limit(50).stream())
    rows = []
    for doc in docs:
        data = _doc_to_dict(doc)
        pc = int(data.get("post_count", 0) or 0)
        if pc < min_posts:
            continue
        rows.append({
            "ticker": data.get("ticker"),
            "post_count": pc,
            "notable_discussions": data.get("notable_discussions") or [],
            "top_post_titles": [
                p.get("title", "") for p in (data.get("top_posts") or [])[:3]
            ],
            "subreddits": list({
                p.get("subreddit", "") for p in (data.get("top_posts") or [])
            }),
        })
    rows.sort(key=lambda r: r.get("post_count", 0), reverse=True)
    return rows[:limit]


def get_earnings_intel(market: str = "US", limit: int = 5) -> list[dict[str, Any]]:
    """Return recent earnings intel docs — beats/misses with context."""
    db = _ensure_app()
    docs = (
        db.collection("tm_earnings_intel")
        .where("market", "==", market)
        .order_by("event_date", direction="DESCENDING")
        .limit(limit)
        .stream()
    )
    rows = []
    for doc in docs:
        data = _doc_to_dict(doc)
        inputs = data.get("inputs") or {}
        earnings_event = inputs.get("earnings_event") or {}
        actuals = inputs.get("reported_actuals") or {}
        rows.append({
            "ticker": earnings_event.get("ticker"),
            "company": earnings_event.get("company"),
            "event_date": data.get("event_date"),
            "surprise_label": actuals.get("surprise_label"),
            "eps_surprise_pct": actuals.get("eps_surprise_pct"),
            "status": inputs.get("timing", {}).get("status"),
            "reddit_present": inputs.get("reddit_present"),
        })
    return rows


def get_stock_name(instrument_id: str) -> str | None:
    """Look up the human-readable company name from tm_stock_facts."""
    db = _ensure_app()
    doc = db.collection("tm_stock_facts").document(instrument_id).get()
    if not doc.exists:
        return None
    data = _doc_to_dict(doc)
    return data.get("name") or data.get("ticker")


def best_story_picks(market: str = "US", n: int = 5) -> list[dict[str, Any]]:
    """Return the best picks for story-driven scripts.

    Combines daily anomalies (biggest moves with narrative context) and
    reddit buzz. Each pick has: ticker, name, change_pct, headline, catalyst,
    thesis, reddit_posts, reddit_discussions. The name field is critical —
    scripts use the company name, NOT the ticker symbol, because the Runway
    avatar can't pronounce symbols like AMAT.
    """
    picks: list[dict[str, Any]] = []

    # 1. Daily anomalies — these already have headlines, catalysts, theses
    anomalies = get_daily_anomalies(market, limit=n * 2)
    for a in anomalies:
        picks.append({
            "ticker": a.get("ticker"),
            "name": a.get("name") or a.get("ticker"),
            "change_pct": a.get("day_change_pct"),
            "headline": a.get("headline"),
            "catalyst": a.get("catalyst"),
            "thesis": a.get("thesis"),
            "sector": a.get("sector"),
            "direction": a.get("direction"),
            "overall_label": a.get("overall_label"),
            "source": "anomaly",
        })

    # 2. Reddit buzz — merge in post counts for tickers already in picks
    reddit = get_reddit_buzz(min_posts=10, limit=10)
    reddit_by_ticker = {r["ticker"]: r for r in reddit if r.get("ticker")}
    for pick in picks:
        t = pick.get("ticker")
        if t and t in reddit_by_ticker:
            r = reddit_by_ticker[t]
            pick["reddit_posts"] = r.get("post_count")
            pick["reddit_discussions"] = r.get("notable_discussions", [])
            pick["reddit_titles"] = r.get("top_post_titles", [])

    # 3. Add pure reddit picks not already in anomalies
    existing_tickers = {p.get("ticker") for p in picks}
    for r in reddit:
        t = r.get("ticker")
        if t and t not in existing_tickers:
            picks.append({
                "ticker": t,
                "name": t,
                "reddit_posts": r.get("post_count"),
                "reddit_discussions": r.get("notable_discussions", []),
                "reddit_titles": r.get("top_post_titles", []),
                "source": "reddit",
            })

    return picks[:n]


def smoke_test() -> dict[str, Any]:
    """Return a small summary so you can verify the connection works."""
    universe = get_active_universe("US")
    heat = get_heat_list("US")
    anomalies = get_daily_anomalies("US", limit=5)
    reddit = get_reddit_buzz(min_posts=10, limit=3)
    return {
        "active_universe_us": universe,
        "heat_list_rows": len(heat.get("rows", [])) if heat else 0,
        "anomaly_count": len(anomalies),
        "top_anomalies": [
            f"{a.get('name')} ({a.get('ticker')}): {a.get('day_change_pct', 0):+.1f}%"
            for a in anomalies[:3]
        ],
        "reddit_buzz": [
            f"{r.get('ticker')}: {r.get('post_count')} posts"
            for r in reddit
        ],
        "now": datetime.now(timezone.utc).isoformat(),
    }


def get_topic_history(topic_key: str) -> dict[str, Any] | None:
    """Return durable history for a topic fingerprint, if present."""
    db = _ensure_app()
    doc = db.collection(SHORT_TOPIC_HISTORY_COLLECTION).document(topic_key).get()
    return _doc_to_dict(doc) if doc.exists else None


def is_recent_topic(topic_key: str, *, cooldown_days: int = 7) -> bool:
    """True when this topic has been posted within the cooldown window."""
    history = get_topic_history(topic_key)
    if not history:
        return False

    posted_at = _coerce_datetime(history.get("last_posted_at") or history.get("posted_at"))
    if posted_at is None:
        return True
    return posted_at >= datetime.now(timezone.utc) - timedelta(days=cooldown_days)


def mark_topic_posted(
    topic_key: str,
    *,
    market: str,
    pick: dict[str, Any],
    title: str,
    description: str,
    video_url: str | None = None,
    service: str | None = None,
) -> None:
    """Persist the fact that a topic was posted so future runs can skip it."""
    db = _ensure_app()
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "topic_key": topic_key,
        "market": market.upper(),
        "ticker": pick.get("ticker"),
        "name": pick.get("name"),
        "headline": pick.get("headline"),
        "catalyst": pick.get("catalyst"),
        "thesis": pick.get("thesis"),
        "source": pick.get("source"),
        "title": title,
        "description": description,
        "video_url": video_url,
        "service": service,
        "last_posted_at": now,
        "updated_at": now,
    }
    db.collection(SHORT_TOPIC_HISTORY_COLLECTION).document(topic_key).set(payload, merge=True)
