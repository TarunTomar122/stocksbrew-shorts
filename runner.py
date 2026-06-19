#!/usr/bin/env python3
"""
Cron-driven orchestrator for the brainrot short pipeline.

Drop a script JSON into scripts/queue/, then run:

    python runner.py                 # process the next script in queue
    python runner.py --max 5         # process up to 5
    python runner.py --dry-run       # show the queue
    python runner.py --loop          # keep polling (use for long-running cron)

Script JSON format:
{
  "id": "nvda-2026-06-18",          // optional, auto-generated if missing
  "text": "NVDA just ripped 4 percent higher and nobody saw it coming.",
  "avatar": "rae2",                  // optional, default rae2
  "gameplay_id": "bg-01",            // optional, picks random from catalog
  "gameplay_tags": ["brainrot"],     // optional, filter catalog
  "output": "output/brainrot/x.mp4"  // optional, auto-generated
}
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from lib import avatar, brainrot, catalog, clipper, hosting, buffer, storygen, transcribe

ROOT = Path(__file__).resolve().parent
QUEUE = ROOT / "scripts" / "queue"
DONE = ROOT / "scripts" / "done"
FAILED = ROOT / "scripts" / "failed"
OUTPUT = ROOT / "output" / "brainrot"
TRANSCRIPT_CACHE = ROOT / ".cache" / "transcripts"


def _setup_dirs() -> None:
    for d in (QUEUE, DONE, FAILED, OUTPUT, TRANSCRIPT_CACHE):
        d.mkdir(parents=True, exist_ok=True)


def _safe_stem(text: str, max_len: int = 30) -> str:
    import re
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text[:80]).strip("-").lower()
    return s[:max_len] or "short"


def process_script(script: dict) -> Path | None:
    """Run the full pipeline for one script. Returns output path or None on failure."""
    _setup_dirs()
    dialogue = script.get("dialogue", [])
    text = script.get("text", "").strip()
    
    if not dialogue and not text:
        print(f"  Skipping: no dialogue or text ({script.get('id', '?')})")
        return None

    script_id = script.get("id") or f"{_safe_stem(text or 'dialogue')}-{uuid.uuid4().hex[:6]}"

    # Determine if this is a dialogue or single-speaker script
    is_dialogue = bool(dialogue)

    if is_dialogue:
        print(f"\n[{script_id}] dialogue ({len(dialogue)} lines)")
        for line in dialogue:
            print(f"  {line.get('character', '?')}: {line.get('text', '')[:60]}")

        print("  [1/3] generating dialogue avatar videos...")
        dialogue_result = avatar.generate_dialogue(dialogue)
        avatar_video = dialogue_result.video_path
        duration = dialogue_result.duration
        print(f"    -> {avatar_video.name} ({duration:.1f}s, {len(dialogue_result.lines)} lines)")

        # Build dialogue_lines for brainrot speaker switching
        dialogue_lines = [
            {
                "character": line.character,
                "text": line.text,
                "start_time": line.start_time,
                "end_time": line.end_time,
            }
            for line in dialogue_result.lines
        ]
    else:
        avatar_name = script.get("avatar", "rae2")
        print(f"\n[{script_id}] avatar={avatar_name}")
        print(f"  text: {text[:80]}{'...' if len(text) > 80 else ''}")

        print("  [1/3] generating avatar video...")
        avatar_result = avatar.generate(text, avatar=avatar_name)
        avatar_video = avatar_result.video_path
        duration = avatar_result.duration
        dialogue_lines = None
        print(f"    -> {avatar_video.name} ({duration:.1f}s)")

    print("  [2/3] transcribing for subtitles...")
    words = transcribe.transcribe_with_cache(avatar_video, TRANSCRIPT_CACHE)
    print(f"    -> {len(words)} words")

    print("  [3/3] composing brainrot...")
    speaker_path = ROOT / "assets" / "speaker" / "charimage.png"
    if not speaker_path.exists():
        speaker_path = None

    if script.get("gameplay_id"):
        gp_item = catalog.pick("gameplay", item_id=script["gameplay_id"])
    else:
        gp_item = catalog.pick("gameplay", tags=script.get("gameplay_tags", ["brainrot"]))
    gameplay_path = catalog.resolve_path(gp_item)
    print(f"    gameplay: {gp_item['id']}")

    output = Path(script["output"]) if script.get("output") else OUTPUT / f"{script_id}.mp4"
    if not output.is_absolute():
        output = ROOT / output

    brainrot.build(
        avatar_video=avatar_video,
        gameplay=gameplay_path,
        speaker=speaker_path,
        output=output,
        duration=duration,
        words=words,
        components=script.get("components"),
        dialogue_lines=dialogue_lines,
    )
    size_mb = output.stat().st_size / 1024 / 1024
    print(f"    -> {output} ({size_mb:.1f}MB)")

    # Upload + schedule step
    if not script.get("skip_upload"):
        print("  [4/4] uploading to Cloudinary + scheduling on Buffer...")
        try:
            video_url = hosting.upload_video(output, folder="stocksbrew-shorts")
            print(f"    -> Cloudinary: {video_url[:80]}...")

            # Build caption from dialogue or text
            caption = _build_caption(script)
            due_at = datetime.now() + timedelta(minutes=1)

            results = buffer.schedule_to_youtube_and_instagram(
                video_url=video_url,
                text=caption,
                due_at=due_at,
            )
            for r in results:
                status = r.get("status", "?")
                channel = r.get("channel", "?")
                service = r.get("service", "?")
                due = r.get("dueAt", "?")
                print(f"    -> {service} ({channel}): {status} at {due}")
        except Exception as e:
            print(f"    -> Upload/schedule failed: {e}")
    else:
        print("  [skip] upload disabled")

    return output


def _build_caption(script: dict) -> str:
    """Build a social media caption from the script data."""
    name = script.get("name", "")
    ticker = script.get("ticker", "")
    dialogue = script.get("dialogue", [])
    text = script.get("text", "")

    # Use the first line of dialogue or the text
    if dialogue:
        hook = dialogue[0].get("text", "")
    elif text:
        hook = text
    else:
        hook = ""

    # Build caption
    parts = []
    if name:
        parts.append(f"{name}")
    if hook:
        parts.append(hook)
    parts.append("#stocks #investing #shorts #stocksbrew")

    return "\n\n".join(parts)


def _move_to(src: Path, dst_dir: Path) -> Path:
    dst = dst_dir / src.name
    shutil.move(str(src), str(dst))
    return dst


def run_queue(max_n: int = 1, loop: bool = False, poll_interval: int = 30) -> int:
    _setup_dirs()
    processed = 0
    while True:
        pending = sorted(QUEUE.glob("*.json"))
        if not pending:
            if loop:
                print(f"[{datetime.now().isoformat(timespec='seconds')}] queue empty, sleeping {poll_interval}s...")
                time.sleep(poll_interval)
                continue
            else:
                if processed == 0:
                    print("Queue empty.")
                return processed
        for script_path in pending[:max_n - processed]:
            print(f"\n=== {script_path.name} ===")
            try:
                script = json.loads(script_path.read_text())
                result = process_script(script)
                script_path = _move_to(script_path, DONE)
                if result is None:
                    _move_to(script_path, FAILED)
                processed += 1
            except Exception as e:
                print(f"  FAILED: {e}")
                try:
                    _move_to(script_path, FAILED)
                except Exception:
                    pass
        if not loop or processed >= max_n:
            return processed


def main() -> None:
    p = argparse.ArgumentParser(description="Process queued scripts into brainrot shorts.")
    p.add_argument("--max", type=int, default=1, help="Max scripts to process this run")
    p.add_argument("--loop", action="store_true", help="Keep polling queue (for long-running cron)")
    p.add_argument("--poll-interval", type=int, default=30, help="Seconds between polls in --loop mode")
    p.add_argument("--dry-run", action="store_true", help="Show queue without processing")
    p.add_argument("--clip", action="store_true",
                   help="Re-sample brainrot clips from a source mp4 (interactive)")
    p.add_argument("--clip-source", type=Path, help="Source mp4 to clip from (use with --clip)")
    p.add_argument("--clip-count", type=int, default=20, help="How many clips to cut")
    p.add_argument("--clip-min", type=float, default=20, help="Min clip duration (s)")
    p.add_argument("--clip-max", type=float, default=40, help="Max clip duration (s)")
    p.add_argument("--clip-seed", type=int, help="Random seed for reproducible clipping")
    p.add_argument("--auto", action="store_true",
                   help="Auto-pick top heat-list tickers, generate scripts via OpenAI, then run")
    p.add_argument("--auto-market", default="US", help="Market to pull heat-list from (US, IN)")
    p.add_argument("--auto-count", type=int, default=3, help="How many shorts to auto-produce")
    p.add_argument("--auto-avatar", default="rae2", help="Avatar to use for auto mode")
    p.add_argument("--auto-min-score", type=float, default=20.0,
                   help="Minimum heat_score to consider a ticker")
    p.add_argument("--auto-skip-existing", action="store_true",
                   help="Don't generate a script if one for the same ticker already queued today")
    args = p.parse_args()

    _setup_dirs()

    if args.clip:
        if not args.clip_source:
            raise SystemExit("--clip-source is required with --clip")
        items = clipper.sample_clips(
            source=args.clip_source,
            out_dir=ROOT / "assets" / "gameplay",
            count=args.clip_count,
            min_duration=args.clip_min,
            max_duration=args.clip_max,
            seed=args.clip_seed,
        )
        clipper.update_catalog(items, ROOT / "catalog" / "gameplay.json")
        print(f"\nDone. {len(items)} clips written to assets/gameplay/ and indexed.")
        return

    if args.auto:
        from lib import firebase
        _setup_dirs()
        print(f"Fetching story picks for {args.auto_market}...")
        picks = firebase.best_story_picks(args.auto_market, n=args.auto_count)
        if not picks:
            print("No anomaly or reddit picks found. Run the trace-money pipeline first.")
            return

        # Dedup: check both queue and done directories for today's tickers
        already_processed: set[str] = set()
        today = datetime.now().strftime("%Y%m%d")
        for s in QUEUE.glob("*.json"):
            try:
                data = json.loads(s.read_text())
                ticker = data.get("ticker") or data.get("name")
                if ticker:
                    already_processed.add(ticker.upper())
            except Exception:
                pass
        for s in DONE.glob("*.json"):
            if today in s.name:
                try:
                    data = json.loads(s.read_text())
                    ticker = data.get("ticker") or data.get("name")
                    if ticker:
                        already_processed.add(ticker.upper())
                except Exception:
                    pass

        fresh = [p for p in picks if (p.get("ticker") or "").upper() not in already_processed]
        print(f"  picked: {[(p.get('name', p.get('ticker')), p.get('change_pct')) for p in picks]}")
        if already_processed:
            print(f"  skipping (already processed today): {sorted(already_processed)}")

        if not fresh:
            print("All picks already processed today. Nothing to do.")
            return

        print("Generating scripts via OpenAI...")
        enriched = storygen.generate_scripts(fresh)

        for i, pick in enumerate(enriched, 1):
            ticker = (pick.get("ticker") or "unknown").lower()
            sid = f"{ticker}-{datetime.now().strftime('%Y%m%d')}-{i:02d}"
            script_path = QUEUE / f"{sid}.json"
            script_path.write_text(json.dumps({
                "id": sid,
                "dialogue": pick.get("dialogue", []),
                "text": pick.get("script", ""),  # fallback for single-speaker
                "avatar": args.auto_avatar,
                "ticker": pick.get("ticker"),
                "name": pick.get("name"),
                "change_pct": pick.get("change_pct"),
                "source": pick.get("source", "auto"),
                "components": pick.get("components", []),
            }, indent=2))
            print(f"  queued {sid}")

    if args.auto and args.max > 0:
        n = run_queue(max_n=args.max, loop=args.loop, poll_interval=args.poll_interval)
        print(f"\nProcessed {n} script(s).")
        return

    if args.dry_run:
        pending = sorted(QUEUE.glob("*.json"))
        if not pending:
            print("Queue empty.")
            return
        for s in pending:
            data = json.loads(s.read_text())
            print(f"  {s.name}: {data.get('text', '')[:60]}")
        return

    n = run_queue(max_n=args.max, loop=args.loop, poll_interval=args.poll_interval)
    print(f"\nProcessed {n} script(s).")


if __name__ == "__main__":
    main()
