#!/usr/bin/env python3
"""Summarize manually exported YouTube Studio metrics without fabricating gaps."""
from __future__ import annotations

import csv
import json
import math
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.experiments import EXPERIMENT_PLAN, summarize_metrics


DEFAULT_INPUT = ROOT / "analytics" / "shorts_experiment_metrics.csv"
NUMERIC_FIELDS = {
    "shown_in_feed",
    "engaged_views",
    "stayed_to_watch_pct",
    "swiped_away_pct",
    "avg_view_duration_seconds",
    "avg_percentage_viewed",
    "shorts_feed_share_pct",
    "views",
    "subscriber_change",
}
PERCENT_FIELDS = {
    "stayed_to_watch_pct",
    "swiped_away_pct",
    "shorts_feed_share_pct",
}
COUNT_FIELDS = {"shown_in_feed", "engaged_views", "views", "subscriber_change"}
NONNEGATIVE_FIELDS = NUMERIC_FIELDS - {"subscriber_change"}
REQUIRED_FIELDS = {
    "experiment_id",
    "assignment_id",
    "slot",
    "variant",
    "video_id",
    "published_at",
    "measured_at",
    *NUMERIC_FIELDS,
}


def load_metrics(path: Path) -> list[dict]:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_FIELDS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Missing columns: {', '.join(sorted(missing))}")
        rows = []
        seen_videos = set()
        seen_assignments = set()
        for line, row in enumerate(reader, 2):
            if not any(row.values()):
                continue
            for field in ("experiment_id", "assignment_id", "variant", "video_id"):
                if not row.get(field):
                    raise ValueError(f"Line {line}: {field} is required")
            if row["video_id"] in seen_videos:
                raise ValueError(f"Line {line}: duplicate video_id {row['video_id']}")
            if row["assignment_id"] in seen_assignments:
                raise ValueError(
                    f"Line {line}: duplicate assignment_id {row['assignment_id']}"
                )
            seen_videos.add(row["video_id"])
            seen_assignments.add(row["assignment_id"])
            slot = int(row["slot"])
            if slot not in range(6):
                raise ValueError(f"Line {line}: slot must be 0-5")
            row["slot"] = slot
            if row["variant"] != EXPERIMENT_PLAN[slot]:
                raise ValueError(f"Line {line}: variant does not match slot {slot}")
            try:
                published = datetime.fromisoformat(row["published_at"])
                measured = datetime.fromisoformat(row["measured_at"])
            except (TypeError, ValueError):
                raise ValueError(f"Line {line}: published_at/measured_at must be ISO timestamps")
            if published.utcoffset() is None or measured.utcoffset() is None:
                raise ValueError(f"Line {line}: timestamps must include a timezone")
            try:
                age_hours = (measured - published).total_seconds() / 3600
            except TypeError:
                raise ValueError(
                    f"Line {line}: published_at/measured_at need matching timezones"
                )
            if not 42 <= age_hours <= 54:
                raise ValueError(f"Line {line}: measure each video at roughly 48 hours")
            for field in NUMERIC_FIELDS:
                if row.get(field) not in (None, ""):
                    value = float(row[field])
                    if not math.isfinite(value):
                        raise ValueError(f"Line {line}: {field} must be finite")
                    if field in COUNT_FIELDS and not value.is_integer():
                        raise ValueError(f"Line {line}: {field} must be an integer")
                    if field in NONNEGATIVE_FIELDS and value < 0:
                        raise ValueError(f"Line {line}: {field} cannot be negative")
                    if field in PERCENT_FIELDS and value > 100:
                        raise ValueError(f"Line {line}: {field} must be 0-100")
                    row[field] = value
            stayed = row.get("stayed_to_watch_pct")
            swiped = row.get("swiped_away_pct")
            if stayed not in (None, "") and swiped not in (None, ""):
                if not 99 <= stayed + swiped <= 101:
                    raise ValueError(
                        f"Line {line}: stayed_to_watch_pct and swiped_away_pct "
                        "must total about 100"
                    )
            rows.append(row)
        return rows


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("csv", nargs="?", type=Path, default=DEFAULT_INPUT)
    args = parser.parse_args()
    rows = load_metrics(args.csv)
    if not rows:
        print("No metric rows yet. Export per-video values from YouTube Studio.")
        return
    print(json.dumps(summarize_metrics(rows), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
