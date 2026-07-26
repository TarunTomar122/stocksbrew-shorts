"""Firestore admin client for StocksBrew market data and Shorts state.

Uses the service account JSON configured via FIREBASE_CREDENTIALS_PATH.
Market collections are read-only; Shorts history and experiment collections
are written transactionally by the publishing pipeline.
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
SHORT_EXPERIMENTS_COLLECTION = "tm_short_experiments"
SHORT_ASSIGNMENTS_COLLECTION = "tm_short_experiment_assignments"
SHORT_PUBLICATIONS_COLLECTION = "tm_short_publications"


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
        visual = a.get("visual_summary") or {}
        catalyst_cards = visual.get("catalyst_cards") or []
        risk_cards = visual.get("risk_cards") or []
        key_points = a.get("key_points") or []
        proof = (
            str(key_points[0])
            .split(" — ", 1)[0]
            .split(" but ", 1)[0]
            .rstrip(" ,;:-")
            if key_points
            else None
        )
        catalyst_card = catalyst_cards[0] if catalyst_cards else {}
        event = catalyst_card.get("event") or a.get("catalyst")
        window = catalyst_card.get("window")
        checkpoint = (
            f"{event} progress over the next {window}"
            if event and window in {"week", "quarter", "year"}
            else f"{event} progress"
            if event
            else None
        )
        risk_card = risk_cards[0] if risk_cards else {}
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
            "proof": proof,
            "checkpoint": checkpoint,
            "invalidation": risk_card.get("trigger") or a.get("risk"),
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


def get_recent_topic_history(
    *, cooldown_days: int = 7, limit: int = 100
) -> list[dict[str, Any]]:
    """Return recent durable topics for ticker-angle similarity checks."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=cooldown_days)
    db = _ensure_app()
    by_key = {}
    for field in ("last_scheduled_at", "last_posted_at"):
        docs = (
            db.collection(SHORT_TOPIC_HISTORY_COLLECTION)
            .order_by(field, direction="DESCENDING")
            .limit(limit)
            .stream()
        )
        for doc in docs:
            data = _doc_to_dict(doc)
            event_at = _coerce_datetime(data.get(field))
            if event_at and event_at >= cutoff:
                by_key[doc.id] = data
    return list(by_key.values())[:limit]


def _scheduled_topic_payload(
    topic_key: str,
    market: str,
    pick: dict[str, Any],
    title: str,
    description: str,
    video_url: str,
    now: datetime,
) -> dict[str, Any]:
    return {
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
        "service": "buffer",
        "last_scheduled_at": now,
        "updated_at": now,
    }


def get_active_experiment_assignment(experiment_id: str) -> dict[str, Any] | None:
    db = _ensure_app()
    state = db.collection(SHORT_EXPERIMENTS_COLLECTION).document(experiment_id).get()
    if not state.exists:
        return None
    active_id = (_doc_to_dict(state)).get("active_assignment_id")
    if not active_id:
        return None
    assignment = db.collection(SHORT_ASSIGNMENTS_COLLECTION).document(active_id).get()
    if not assignment.exists:
        raise RuntimeError(f"Experiment {experiment_id} points to missing assignment {active_id}")
    return _doc_to_dict(assignment)


def get_experiment_state(experiment_id: str) -> dict[str, Any]:
    doc = (
        _ensure_app()
        .collection(SHORT_EXPERIMENTS_COLLECTION)
        .document(experiment_id)
        .get()
    )
    return _doc_to_dict(doc) if doc.exists else {}


def get_experiment_assignment(assignment_id: str) -> dict[str, Any] | None:
    doc = (
        _ensure_app()
        .collection(SHORT_ASSIGNMENTS_COLLECTION)
        .document(assignment_id)
        .get()
    )
    return _doc_to_dict(doc) if doc.exists else None


def reserve_experiment_assignment(
    experiment_id: str,
    plan: tuple[str, ...],
    topic_key: str,
    pick: dict[str, Any],
    *,
    min_interval_hours: int,
) -> dict[str, Any]:
    """Atomically reserve one durable experiment slot or return its current gate."""
    from firebase_admin import firestore
    from lib.experiments import assignment_id, previous_publication_verified

    if min_interval_hours < 48:
        raise ValueError("Experiment publish interval cannot be less than 48 hours")
    db = _ensure_app()
    state_ref = db.collection(SHORT_EXPERIMENTS_COLLECTION).document(experiment_id)
    transaction = db.transaction()

    @firestore.transactional
    def reserve(txn):
        state_snap = state_ref.get(transaction=txn)
        state = _doc_to_dict(state_snap) if state_snap.exists else {}
        stored_plan = tuple(state.get("plan") or ())
        if stored_plan and stored_plan != plan:
            raise RuntimeError(f"Experiment {experiment_id} plan changed after it started")
        active_id = state.get("active_assignment_id")
        if active_id:
            active_ref = db.collection(SHORT_ASSIGNMENTS_COLLECTION).document(active_id)
            active_snap = active_ref.get(transaction=txn)
            if not active_snap.exists:
                raise RuntimeError(
                    f"Experiment {experiment_id} points to missing assignment {active_id}"
                )
            return {"outcome": "active", **_doc_to_dict(active_snap)}

        slot = int(state.get("next_slot", 0))
        if slot >= len(plan):
            return {"outcome": "complete", "next_slot": slot}
        if not previous_publication_verified(state, slot):
            return {
                "outcome": "awaiting_publication",
                "previous_slot": slot - 1,
                "assignment_id": state.get("last_scheduled_assignment_id"),
            }

        last_scheduled = _coerce_datetime(
            state.get("last_scheduled_at") or state.get("last_published_at")
        )
        now = datetime.now(timezone.utc)
        if last_scheduled:
            next_at = last_scheduled + timedelta(hours=min_interval_hours)
            if next_at > now:
                return {"outcome": "waiting", "next_at": next_at}

        aid = assignment_id(experiment_id, slot, topic_key)
        assignment_ref = db.collection(SHORT_ASSIGNMENTS_COLLECTION).document(aid)
        assignment_snap = assignment_ref.get(transaction=txn)
        if assignment_snap.exists:
            assignment = _doc_to_dict(assignment_snap)
        else:
            assignment = {
                "assignment_id": aid,
                "experiment_id": experiment_id,
                "slot": slot,
                "variant": plan[slot],
                "topic_class": pick.get("topic_class"),
                "topic_key": topic_key,
                "pick": pick,
                "status": "assigned",
                "created_at": now,
                "updated_at": now,
            }
            txn.set(assignment_ref, assignment)
        txn.set(
            state_ref,
            {
                "experiment_id": experiment_id,
                "plan": list(plan),
                "next_slot": slot,
                "active_assignment_id": aid,
                "updated_at": now,
            },
            merge=True,
        )
        return {"outcome": "assigned", **assignment}

    return reserve(transaction)


def save_experiment_script(assignment_id: str, script: dict[str, Any]) -> None:
    set_experiment_assignment_status(assignment_id, "generated", script=script)


_ASSIGNMENT_TRANSITIONS = {
    "assigned": {"generated", "failed"},
    "generated": {"rendered", "failed"},
    "rendered": {"uploaded", "failed"},
    "uploaded": {"scheduling", "needs_reconciliation", "failed"},
    "failed": {"generated", "rendered"},
    "scheduling": {"needs_reconciliation", "scheduled"},
    "needs_reconciliation": set(),
    "scheduled": {"published"},
    "published": set(),
}


def set_experiment_assignment_status(
    assignment_id: str,
    status: str,
    **details: Any,
) -> None:
    from firebase_admin import firestore

    db = _ensure_app()
    ref = db.collection(SHORT_ASSIGNMENTS_COLLECTION).document(assignment_id)
    transaction = db.transaction()

    @firestore.transactional
    def transition(txn):
        snap = ref.get(transaction=txn)
        if not snap.exists:
            raise RuntimeError(f"Missing experiment assignment {assignment_id}")
        current = (_doc_to_dict(snap)).get("status")
        if current != status and status not in _ASSIGNMENT_TRANSITIONS.get(current, set()):
            raise RuntimeError(f"Invalid assignment transition {current} -> {status}")
        txn.set(
            ref,
            {"status": status, "updated_at": datetime.now(timezone.utc), **details},
            merge=True,
        )

    transition(transaction)


def begin_scheduling(topic_key: str, assignment_id: str) -> str:
    """Enter the irreversible Buffer step once; ambiguous retries are blocked."""
    from firebase_admin import firestore

    db = _ensure_app()
    ref = db.collection(SHORT_PUBLICATIONS_COLLECTION).document(topic_key)
    transaction = db.transaction()

    @firestore.transactional
    def begin(txn):
        snap = ref.get(transaction=txn)
        current = _doc_to_dict(snap) if snap.exists else {}
        status = current.get("status")
        if status in {"scheduled", "published"}:
            return "scheduled"
        if status in {"scheduling", "publishing", "needs_reconciliation"}:
            raise RuntimeError(
                f"Publication {topic_key} is {status}; reconcile Buffer before retrying"
            )
        txn.set(
            ref,
            {
                "topic_key": topic_key,
                "assignment_id": assignment_id,
                "status": "scheduling",
                "results": [],
                "updated_at": datetime.now(timezone.utc),
            },
            merge=True,
        )
        return "scheduling"

    return begin(transaction)


def mark_publication_uncertain(topic_key: str, error: str) -> bool:
    from firebase_admin import firestore

    db = _ensure_app()
    ref = db.collection(SHORT_PUBLICATIONS_COLLECTION).document(topic_key)
    transaction = db.transaction()

    @firestore.transactional
    def mark(txn):
        snap = ref.get(transaction=txn)
        current = _doc_to_dict(snap) if snap.exists else {}
        if current.get("status") in {"scheduled", "published"}:
            return False
        txn.set(
            ref,
            {
                "status": "needs_reconciliation",
                "error": error,
                "updated_at": datetime.now(timezone.utc),
            },
            merge=True,
        )
        return True

    return mark(transaction)


def record_scheduling_results(topic_key: str, results: list[dict[str, Any]]) -> None:
    """Persist raw Buffer responses before validation/finalization."""
    from firebase_admin import firestore

    db = _ensure_app()
    ref = db.collection(SHORT_PUBLICATIONS_COLLECTION).document(topic_key)
    transaction = db.transaction()

    @firestore.transactional
    def record(txn):
        snap = ref.get(transaction=txn)
        current = _doc_to_dict(snap) if snap.exists else {}
        if current.get("status") != "scheduling":
            raise RuntimeError(f"Publication {topic_key} was not armed")
        now = datetime.now(timezone.utc)
        txn.set(
            ref,
            {
                "results": results,
                "buffer_responded_at": now,
                "updated_at": now,
            },
            merge=True,
        )

    record(transaction)


def complete_scheduling(
    *,
    topic_key: str,
    market: str,
    pick: dict[str, Any],
    title: str,
    description: str,
    video_url: str,
    results: list[dict[str, Any]] | None,
    experiment_id: str | None = None,
    assignment_id: str | None = None,
    expected_status: str = "scheduling",
    reconciliation_evidence: str | None = None,
) -> None:
    """Atomically record Buffer acceptance and advance an experiment when present."""
    from firebase_admin import firestore

    db = _ensure_app()
    publication_ref = db.collection(SHORT_PUBLICATIONS_COLLECTION).document(topic_key)
    topic_ref = db.collection(SHORT_TOPIC_HISTORY_COLLECTION).document(topic_key)
    state_ref = (
        db.collection(SHORT_EXPERIMENTS_COLLECTION).document(experiment_id)
        if experiment_id
        else None
    )
    assignment_ref = (
        db.collection(SHORT_ASSIGNMENTS_COLLECTION).document(assignment_id)
        if assignment_id
        else None
    )
    transaction = db.transaction()

    @firestore.transactional
    def finish(txn):
        publication_snap = publication_ref.get(transaction=txn)
        publication = _doc_to_dict(publication_snap) if publication_snap.exists else {}
        if publication.get("status") in {"scheduled", "published"}:
            return
        if publication.get("status") != expected_status:
            raise RuntimeError(f"Publication {topic_key} was not armed")
        final_results = results if results is not None else publication.get("results") or []

        state = assignment = None
        if state_ref and assignment_ref:
            state_snap = state_ref.get(transaction=txn)
            assignment_snap = assignment_ref.get(transaction=txn)
            if not assignment_snap.exists:
                raise RuntimeError(f"Missing experiment assignment {assignment_id}")
            state = _doc_to_dict(state_snap) if state_snap.exists else {}
            assignment = _doc_to_dict(assignment_snap)
            if assignment.get("experiment_id") != experiment_id:
                raise RuntimeError(
                    f"Assignment {assignment_id} belongs to another experiment"
                )
            if assignment.get("topic_key") != topic_key:
                raise RuntimeError(f"Assignment {assignment_id} topic changed")
            if state.get("active_assignment_id") != assignment_id:
                raise RuntimeError(f"Assignment {assignment_id} is not active")
            if assignment.get("status") != expected_status:
                raise RuntimeError(f"Assignment {assignment_id} was not armed")

        now = datetime.now(timezone.utc)
        txn.set(
            publication_ref,
            {
                "status": "scheduled",
                "video_url": video_url,
                "results": final_results,
                "scheduled_at": now,
                "updated_at": now,
                "reconciliation_evidence": reconciliation_evidence,
            },
            merge=True,
        )
        txn.set(
            topic_ref,
            _scheduled_topic_payload(
                topic_key, market, pick, title, description, video_url, now
            ),
            merge=True,
        )
        if state_ref and assignment_ref and state is not None and assignment is not None:
            txn.set(
                assignment_ref,
                {
                    "status": "scheduled",
                    "video_url": video_url,
                    "results": final_results,
                    "scheduled_at": now,
                    "updated_at": now,
                    "reconciliation_evidence": reconciliation_evidence,
                },
                merge=True,
            )
            txn.set(
                state_ref,
                {
                    "active_assignment_id": None,
                    "next_slot": int(assignment.get("slot", 0)) + 1,
                    "scheduled_count": int(state.get("scheduled_count", 0)) + 1,
                    "last_scheduled_at": now,
                    "last_scheduled_slot": int(assignment.get("slot", 0)),
                    "last_scheduled_assignment_id": assignment_id,
                    "updated_at": now,
                },
                merge=True,
            )

    finish(transaction)


def reconcile_experiment_scheduling(
    assignment_id: str,
    resolution: str,
    evidence: str,
) -> None:
    """Resolve a terminal ambiguous Buffer submission with operator evidence."""
    if resolution not in {"scheduled", "retry"} or not evidence.strip():
        raise ValueError("Resolution and evidence are required")

    db = _ensure_app()
    assignment = get_experiment_assignment(assignment_id)
    if not assignment:
        raise RuntimeError(f"Missing experiment assignment {assignment_id}")
    experiment_id = assignment["experiment_id"]
    topic_key = assignment["topic_key"]
    script = assignment.get("script") or {}

    if resolution == "scheduled":
        video_url = assignment.get("video_url")
        if not video_url:
            raise RuntimeError("Cannot confirm scheduling without an uploaded video URL")
        complete_scheduling(
            experiment_id=experiment_id,
            assignment_id=assignment_id,
            topic_key=topic_key,
            market=script.get("market", "US"),
            pick=script or assignment.get("pick") or {},
            title=script.get("title", ""),
            description=script.get("description", ""),
            video_url=video_url,
            results=None,
            expected_status="needs_reconciliation",
            reconciliation_evidence=evidence,
        )
        return

    from firebase_admin import firestore

    state_ref = db.collection(SHORT_EXPERIMENTS_COLLECTION).document(experiment_id)
    assignment_ref = db.collection(SHORT_ASSIGNMENTS_COLLECTION).document(assignment_id)
    publication_ref = db.collection(SHORT_PUBLICATIONS_COLLECTION).document(topic_key)
    transaction = db.transaction()

    @firestore.transactional
    def reset(txn):
        state_snap = state_ref.get(transaction=txn)
        assignment_snap = assignment_ref.get(transaction=txn)
        publication_snap = publication_ref.get(transaction=txn)
        state = _doc_to_dict(state_snap) if state_snap.exists else {}
        current_assignment = (
            _doc_to_dict(assignment_snap) if assignment_snap.exists else {}
        )
        publication = _doc_to_dict(publication_snap) if publication_snap.exists else {}
        if state.get("active_assignment_id") != assignment_id:
            raise RuntimeError(f"Assignment {assignment_id} is not active")
        if current_assignment.get("status") != "needs_reconciliation":
            raise RuntimeError(f"Assignment {assignment_id} is not reconcilable")
        if publication.get("status") != "needs_reconciliation":
            raise RuntimeError(f"Publication {topic_key} is not reconcilable")
        now = datetime.now(timezone.utc)
        audit = {"resolution": "retry", "evidence": evidence, "resolved_at": now}
        txn.set(
            assignment_ref,
            {"status": "rendered", "last_reconciliation": audit, "updated_at": now},
            merge=True,
        )
        txn.set(
            publication_ref,
            {
                "status": "retryable",
                "error": None,
                "last_reconciliation": audit,
                "updated_at": now,
            },
            merge=True,
        )

    reset(transaction)


def confirm_experiment_published(
    assignment_id: str,
    youtube_video_id: str,
    evidence: str,
) -> None:
    """Promote Buffer-scheduled state only after live YouTube verification."""
    if not youtube_video_id.strip() or not evidence.strip():
        raise ValueError("YouTube video ID and evidence are required")
    from firebase_admin import firestore

    db = _ensure_app()
    assignment_ref = db.collection(SHORT_ASSIGNMENTS_COLLECTION).document(assignment_id)
    assignment = get_experiment_assignment(assignment_id)
    if not assignment:
        raise RuntimeError(f"Missing experiment assignment {assignment_id}")
    topic_key = assignment["topic_key"]
    experiment_id = assignment["experiment_id"]
    slot = int(assignment["slot"])
    publication_ref = db.collection(SHORT_PUBLICATIONS_COLLECTION).document(topic_key)
    topic_ref = db.collection(SHORT_TOPIC_HISTORY_COLLECTION).document(topic_key)
    state_ref = db.collection(SHORT_EXPERIMENTS_COLLECTION).document(experiment_id)
    transaction = db.transaction()

    @firestore.transactional
    def confirm(txn):
        assignment_snap = assignment_ref.get(transaction=txn)
        publication_snap = publication_ref.get(transaction=txn)
        state_snap = state_ref.get(transaction=txn)
        current_assignment = (
            _doc_to_dict(assignment_snap) if assignment_snap.exists else {}
        )
        publication = _doc_to_dict(publication_snap) if publication_snap.exists else {}
        state = _doc_to_dict(state_snap) if state_snap.exists else {}
        already_published = current_assignment.get("status") == "published"
        if already_published:
            if (
                current_assignment.get("youtube_video_id") != youtube_video_id
                or publication.get("status") != "published"
                or publication.get("youtube_video_id") != youtube_video_id
            ):
                raise RuntimeError(f"Assignment {assignment_id} YouTube video changed")
        else:
            if current_assignment.get("status") != "scheduled":
                raise RuntimeError(f"Assignment {assignment_id} is not scheduled")
            if current_assignment.get("topic_key") != topic_key:
                raise RuntimeError(f"Assignment {assignment_id} topic changed")
            if publication.get("status") != "scheduled":
                raise RuntimeError(f"Publication {topic_key} is not scheduled")
        now = datetime.now(timezone.utc)
        if not already_published:
            proof = {
                "status": "published",
                "youtube_video_id": youtube_video_id,
                "publish_evidence": evidence,
                "published_at": now,
                "updated_at": now,
            }
            txn.set(assignment_ref, proof, merge=True)
            txn.set(publication_ref, proof, merge=True)
            txn.set(
                topic_ref,
                {
                    "youtube_video_id": youtube_video_id,
                    "last_published_at": now,
                    "updated_at": now,
                },
                merge=True,
            )
        if slot >= int(state.get("last_published_slot", -1)):
            txn.set(
                state_ref,
                {
                    "last_published_slot": slot,
                    "last_published_assignment_id": assignment_id,
                    "updated_at": now,
                },
                merge=True,
            )

    confirm(transaction)
