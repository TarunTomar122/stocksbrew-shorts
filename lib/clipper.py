"""Cut N random sequences from a long source video into reusable bg modules."""
from __future__ import annotations

import json
import random
from pathlib import Path

from .ffmpeg import probe, run


def cut(source: Path, start: float, duration: float, dst: Path, crf: int = 20) -> None:
    run([
        "ffmpeg", "-y",
        "-ss", f"{start:.3f}",
        "-i", str(source),
        "-t", f"{duration:.3f}",
        "-an",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", str(crf),
        str(dst),
    ])


def sample_clips(
    source: Path,
    out_dir: Path,
    count: int = 20,
    min_duration: float = 20,
    max_duration: float = 40,
    min_gap: float = 2.0,
    seed: int | None = None,
    prefix: str = "bg",
) -> list[dict]:
    """Cut N random sequences from `source` into `out_dir`. Returns metadata list."""
    out_dir.mkdir(parents=True, exist_ok=True)
    total = probe(source)[2]
    rng = random.Random(seed)
    items = []
    for i in range(count):
        dur = rng.uniform(min_duration, max_duration)
        max_start = max(0.0, total - dur - 0.1)
        start = rng.uniform(0.0, max_start)
        idx = i + 1
        out = out_dir / f"{prefix}_{idx:02d}_{int(dur)}s.mp4"
        print(f"[{idx:02d}/{count}] {start:6.1f}s +{dur:5.1f}s -> {out.name}")
        cut(source, start, dur, out)
        items.append({
            "id": f"{prefix}-{idx:02d}",
            "path": str(out),
            "start": round(start, 2),
            "duration": round(dur, 2),
            "tags": [prefix, f"duration-{int(dur)}"],
        })
    return items


def update_catalog(items: list[dict], catalog_path: Path) -> None:
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict = {"items": []}
    if catalog_path.exists():
        raw = json.loads(catalog_path.read_text())
        if isinstance(raw, list):
            existing = {"items": raw}
        elif isinstance(raw, dict):
            existing = raw
    by_path = {it.get("path"): it for it in existing.get("items", [])}
    for it in items:
        by_path[it["path"]] = it
    existing["items"] = list(by_path.values())
    catalog_path.write_text(json.dumps(existing, indent=2))
