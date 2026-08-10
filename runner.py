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
from datetime import datetime
from pathlib import Path



ROOT = Path(__file__).resolve().parent
QUEUE = ROOT / "scripts" / "queue"
DONE = ROOT / "scripts" / "done"
FAILED = ROOT / "scripts" / "failed"
OUTPUT = ROOT / "output" / "brainrot"
TRANSCRIPT_CACHE = ROOT / ".cache" / "transcripts"


def _event(state: str, **details) -> None:
    print(json.dumps({"event": state, **details}, default=str, sort_keys=True))


def _setup_dirs() -> None:
    for d in (QUEUE, DONE, FAILED, OUTPUT, TRANSCRIPT_CACHE):
        d.mkdir(parents=True, exist_ok=True)


def _safe_stem(text: str, max_len: int = 30) -> str:
    import re
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text[:80]).strip("-").lower()
    return s[:max_len] or "short"


def process_script(script: dict, skip_upload: bool = False) -> Path | None:
    """Run the full pipeline for one script. Returns output path or None on failure."""
    from lib import avatar, brainrot, catalog, hosting, buffer, transcribe
    from lib import firebase
    _setup_dirs()
    dialogue = script.get("dialogue", [])
    text = script.get("text", "").strip()
    
    if not dialogue and not text:
        raise ValueError(f"No dialogue or text ({script.get('id', '?')})")

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

    render_settings = script.get("render_settings") or {}
    brainrot.build(
        avatar_video=avatar_video,
        gameplay=gameplay_path,
        speaker=speaker_path,
        output=output,
        duration=duration,
        words=words,
        components=script.get("components") or None,
        dialogue_lines=dialogue_lines,
        speaker_corner=str(render_settings.get("speaker_corner", "bottom-right")),
        speaker_scale=float(render_settings.get("speaker_scale", 0.55)),
        subtitle_margin=int(render_settings.get("subtitle_margin", 320)),
        subtitle_fontsize=int(render_settings.get("subtitle_fontsize", 120)),
    )
    size_mb = output.stat().st_size / 1024 / 1024
    print(f"    -> {output} ({size_mb:.1f}MB)")
    assignment_id = script.get("assignment_id")
    if assignment_id:
        firebase.set_experiment_assignment_status(
            assignment_id,
            "rendered",
            output=str(output),
            size_mb=size_mb,
            duration_seconds=round(duration, 3),
        )
    _event("rendered", script_id=script_id, assignment_id=assignment_id, output=str(output))

    # Upload + schedule step
    if not skip_upload and not script.get("skip_upload"):
        print("  [4/4] uploading to Cloudinary + scheduling on Buffer...")
        try:
            video_url = hosting.upload_video(output, folder="stocksbrew-shorts")
            print(f"    -> Cloudinary: {video_url[:80]}...")
            if assignment_id:
                firebase.set_experiment_assignment_status(
                    assignment_id, "uploaded", video_url=video_url
                )
            _event(
                "uploaded",
                script_id=script_id,
                assignment_id=assignment_id,
                video_url=video_url,
            )
        except Exception as e:
            if assignment_id:
                firebase.set_experiment_assignment_status(
                    assignment_id, "failed", stage="upload", error=str(e)
                )
            _event("failed", stage="upload", script_id=script_id, error=str(e))
            raise

        # Build caption from dialogue or text
        title, description = _build_caption(script)

        # Combine title and description for Buffer
        caption = description if description else f"{title}\n\n#stocks #investing #shorts #stocksbrew"
        topic_key = script.get("topic_key") or f"script-{script_id}"
        armed = False
        try:
            publication_state = firebase.begin_scheduling(
                topic_key, assignment_id or script_id
            )
            if publication_state == "scheduled":
                if assignment_id:
                    firebase.set_experiment_assignment_status(
                        assignment_id,
                        "needs_reconciliation",
                        stage="schedule",
                        error="topic already has a scheduled ledger entry",
                    )
                    raise RuntimeError(
                        f"Topic {topic_key} is already scheduled; reconcile assignment"
                    )
                _event(
                    "scheduled",
                    script_id=script_id,
                    assignment_id=assignment_id,
                    deduplicated=True,
                )
                return output
            armed = True
            if assignment_id:
                firebase.set_experiment_assignment_status(assignment_id, "scheduling")
            _event("scheduling", script_id=script_id, assignment_id=assignment_id)

            results = buffer.schedule_to_youtube_and_instagram(
                video_url=video_url,
                text=caption,
                title=title,
            )
            from lib.experiments import validate_buffer_results
            firebase.record_scheduling_results(topic_key, results)
            validate_buffer_results(results)
            for r in results:
                status = r.get("status", "?")
                channel = r.get("channel", "?")
                service = r.get("service", "?")
                due = r.get("dueAt", "?")
                print(f"    -> {service} ({channel}): {status} at {due}")

            if assignment_id:
                firebase.complete_scheduling(
                    experiment_id=script["experiment_id"],
                    assignment_id=assignment_id,
                    topic_key=topic_key,
                    market=script.get("market", "US"),
                    pick=script,
                    title=title,
                    description=description,
                    video_url=video_url,
                    results=results,
                )
            else:
                firebase.complete_scheduling(
                    topic_key=topic_key,
                    market=script.get("market", "US"),
                    pick=script,
                    title=title,
                    description=description,
                    video_url=video_url,
                    results=results,
                )
            _event(
                "scheduled",
                script_id=script_id,
                assignment_id=assignment_id,
                services=[r.get("service") for r in results],
                video_url=video_url,
            )
        except Exception as e:
            if armed:
                uncertain = firebase.mark_publication_uncertain(topic_key, str(e))
                if uncertain and assignment_id:
                    firebase.set_experiment_assignment_status(
                        assignment_id,
                        "needs_reconciliation",
                        stage="schedule",
                        error=str(e),
                    )
            _event("failed", stage="schedule", script_id=script_id, error=str(e))
            raise
    else:
        print("  [skip] upload disabled")

    return output


def _build_caption(script: dict) -> tuple[str, str]:
    """Build a social media caption from the script data. Returns (title, description)."""
    title = script.get("title", "")
    description = script.get("description", "")
    name = script.get("name", "")
    ticker = script.get("ticker", "")
    dialogue = script.get("dialogue", [])
    text = script.get("text", "")

    # Fallback title if not provided
    if not title:
        if name:
            title = f"{name} — Stock Analysis"
        elif ticker:
            title = f"{ticker} — Stock Analysis"
        else:
            title = "Stock Market Update"

    # Fallback description if not provided
    if not description:
        # Use the first line of dialogue or the text
        if dialogue:
            hook = dialogue[0].get("text", "")
        elif text:
            hook = text
        else:
            hook = ""
        description = f"{hook}\n\n#stocks #investing #shorts #stocksbrew"

    return title, description


def _move_to(src: Path, dst_dir: Path) -> Path:
    dst = dst_dir / src.name
    shutil.move(str(src), str(dst))
    return dst


def run_queue(
    max_n: int = 1,
    loop: bool = False,
    poll_interval: int = 30,
    skip_upload: bool = False,
    paths: list[Path] | None = None,
) -> int:
    _setup_dirs()
    processed = 0
    while True:
        pending = (
            [path for path in paths if path.exists()]
            if paths
            else sorted(QUEUE.glob("*.json"))
        )
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
            script = None
            try:
                script = json.loads(script_path.read_text())
                result = process_script(script, skip_upload=skip_upload)
                script_path = _move_to(script_path, DONE)
                if result is None:
                    _move_to(script_path, FAILED)
                processed += 1
            except Exception as e:
                print(f"  FAILED: {e}")
                assignment_id = script.get("assignment_id") if script else None
                if assignment_id:
                    try:
                        from lib import firebase
                        current = firebase.get_experiment_assignment(assignment_id) or {}
                        if current.get("status") in {"assigned", "generated", "rendered"}:
                            firebase.set_experiment_assignment_status(
                                assignment_id, "failed", stage="render", error=str(e)
                            )
                    except RuntimeError:
                        pass
                try:
                    _move_to(script_path, FAILED)
                except Exception:
                    pass
                raise
        if not loop or processed >= max_n:
            return processed


def main() -> None:
    raise SystemExit("Shorts pipeline disabled")

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
    p.add_argument("--auto-history-days", type=int, default=7,
                   help="Lookback window for skipping already-posted topics")
    p.add_argument("--auto-skip-existing", action=argparse.BooleanOptionalAction, default=True,
                   help="Skip topics already posted recently")
    p.add_argument("--experiment", action="store_true",
                   help="Run the controlled six-slot Shorts format experiment")
    p.add_argument("--experiment-interval-hours", type=int, default=48,
                   help="Minimum hours between controlled experiment publications")
    p.add_argument("--reconcile-assignment",
                   help="Resolve one needs_reconciliation experiment assignment")
    p.add_argument("--reconcile-resolution", choices=("scheduled", "retry"))
    p.add_argument("--reconcile-evidence",
                   help="Operator evidence from Buffer/Studio for reconciliation")
    p.add_argument("--confirm-published",
                   help="Promote one scheduled assignment after live YouTube verification")
    p.add_argument("--youtube-video-id")
    p.add_argument("--publish-evidence")

    p.add_argument("--no-upload", action="store_true",
                   help="Skip Cloudinary upload and Buffer scheduling")
    args = p.parse_args()
    if args.experiment and args.experiment_interval_hours < 48:
        p.error("--experiment-interval-hours cannot be less than 48")

    _setup_dirs()

    if args.confirm_published:
        if not args.youtube_video_id or not args.publish_evidence:
            p.error("--youtube-video-id and --publish-evidence are required")
        from lib import firebase
        firebase.confirm_experiment_published(
            args.confirm_published,
            args.youtube_video_id,
            args.publish_evidence,
        )
        _event(
            "published",
            assignment_id=args.confirm_published,
            youtube_video_id=args.youtube_video_id,
            verified=True,
        )
        return

    if args.reconcile_assignment:
        if not args.reconcile_resolution or not args.reconcile_evidence:
            p.error("--reconcile-resolution and --reconcile-evidence are required")
        from lib import firebase
        firebase.reconcile_experiment_scheduling(
            args.reconcile_assignment,
            args.reconcile_resolution,
            args.reconcile_evidence,
        )
        _event(
            "reconciled",
            assignment_id=args.reconcile_assignment,
            resolution=args.reconcile_resolution,
        )
        return

    if args.clip:
        from lib import clipper
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
        from lib import firebase, storygen
        from lib.experiments import (
            EXPERIMENT_ID,
            EXPERIMENT_PLAN,
            build_components,
            format_prompt,
            format_settings,
            rank_story_picks,
        )
        from lib.topic_dedup import dedupe_items, is_near_duplicate, topic_fingerprint
        _setup_dirs()
        auto_paths: list[Path] = []
        assignment = (
            firebase.get_active_experiment_assignment(EXPERIMENT_ID)
            if args.experiment
            else None
        )
        if assignment:
            picks = [assignment["pick"]]
            fresh = picks
            print(f"Resuming experiment assignment {assignment['assignment_id']}")
        else:
            print(f"Fetching story picks for {args.auto_market}...")
            picks = firebase.best_story_picks(
                args.auto_market, n=max(args.auto_count * 4, 10)
            )
            if args.experiment:
                picks = rank_story_picks(picks)
            if not picks:
                _event(
                    "no_fresh_topic",
                    reason=(
                        "no_explainable_hard_moves"
                        if args.experiment
                        else "no_story_picks"
                    ),
                )
                return

            # Local files prevent same-run duplication; Firestore is the durable source.
            blocked_keys: set[str] = set()
            for folder in (QUEUE, DONE, FAILED):
                for s in folder.glob("*.json"):
                    try:
                        data = json.loads(s.read_text())
                        key = data.get("topic_key") or topic_fingerprint(data)
                        blocked_keys.add(key)
                    except Exception:
                        pass

            history = []
            if args.auto_skip_existing:
                history = firebase.get_recent_topic_history(
                    cooldown_days=args.auto_history_days
                )
                blocked_keys.update(
                    item["topic_key"] for item in history if item.get("topic_key")
                )
                picks = [
                    pick for pick in picks if not is_near_duplicate(pick, history)
                ]

            fresh = dedupe_items(picks, blocked_keys)
            print(f"  picked: {[(p.get('name', p.get('ticker')), p.get('change_pct')) for p in picks]}")
            if blocked_keys:
                print(f"  skipping already-seen topics: {len(blocked_keys)} blocked")
            if args.auto_skip_existing:
                print(f"  durable cooldown: {args.auto_history_days} days")

            if not fresh:
                _event("no_fresh_topic", reason="durable_exact_or_near_duplicate")
                return

        if args.dry_run:
            state = firebase.get_experiment_state(EXPERIMENT_ID)
            slot = int(state.get("next_slot", 0))
            variant = (
                assignment.get("variant")
                if assignment
                else EXPERIMENT_PLAN[slot] if slot < len(EXPERIMENT_PLAN) else None
            )
            _event(
                "dry_run",
                assignment_id=assignment.get("assignment_id") if assignment else None,
                assignment_status=assignment.get("status") if assignment else None,
                candidate=fresh[0] if fresh else None,
                experiment_id=EXPERIMENT_ID if args.experiment else None,
                variant=variant if args.experiment else None,
                writes=False,
                upload=False,
            )
            return

        if assignment and assignment.get("status") in {
            "scheduling",
            "needs_reconciliation",
        }:
            raise RuntimeError(
                f"Experiment assignment {assignment['assignment_id']} is "
                f"{assignment['status']}; reconcile Buffer before retrying"
            )

        if args.experiment and not assignment:
            reservation = firebase.reserve_experiment_assignment(
                EXPERIMENT_ID,
                EXPERIMENT_PLAN,
                fresh[0]["topic_key"],
                fresh[0],
                min_interval_hours=args.experiment_interval_hours,
            )
            outcome = reservation.pop("outcome")
            if outcome == "waiting":
                _event("experiment_wait", next_at=reservation["next_at"])
                return
            if outcome == "awaiting_publication":
                _event(
                    "experiment_awaiting_publication",
                    previous_slot=reservation["previous_slot"],
                    assignment_id=reservation.get("assignment_id"),
                )
                return
            if outcome == "complete":
                _event("experiment_complete", experiment_id=EXPERIMENT_ID)
                return
            assignment = reservation
            fresh = [assignment["pick"]]

        if args.experiment:
            variant = assignment["variant"]
            script = assignment.get("script")
            if script:
                _event(
                    "generated",
                    assignment_id=assignment["assignment_id"],
                    variant=variant,
                    recovered=True,
                )
            else:
                generation_pick = {
                    **fresh[0],
                    "experiment_id": EXPERIMENT_ID,
                    "assignment_id": assignment["assignment_id"],
                    "format_variant": variant,
                    "format_instructions": format_prompt(variant),
                }
                try:
                    generated = storygen.generate_script(generation_pick)
                except Exception as e:
                    firebase.set_experiment_assignment_status(
                        assignment["assignment_id"],
                        "failed",
                        stage="generation",
                        error=str(e),
                    )
                    _event("failed", stage="generation", error=str(e))
                    raise
                script = {
                    **generated,
                    "id": assignment["assignment_id"],
                    "market": args.auto_market,
                    "topic_key": assignment["topic_key"],
                    "components": build_components(generated, variant),
                    "render_settings": format_settings(variant),
                }
                firebase.save_experiment_script(assignment["assignment_id"], script)
                _event(
                    "generated",
                    assignment_id=assignment["assignment_id"],
                    variant=variant,
                    ticker=script.get("ticker"),
                )

            script_path = QUEUE / f"{assignment['assignment_id']}.json"
            script_path.write_text(json.dumps(script, indent=2))
            auto_paths.append(script_path)
            print(f"  queued {script['id']} ({variant})")
        else:
            print("Generating scripts via OpenAI...")
            enriched = storygen.generate_scripts(fresh[:args.auto_count])

            for i, pick in enumerate(enriched, 1):
                ticker = (pick.get("ticker") or "unknown").lower()
                sid = f"{ticker}-{datetime.now().strftime('%Y%m%d')}-{i:02d}"
                script_path = QUEUE / f"{sid}.json"
                script_path.write_text(json.dumps({
                        "id": sid,
                        "dialogue": pick.get("dialogue", []),
                        "text": pick.get("script", ""),
                        "avatar": args.auto_avatar,
                        "market": args.auto_market,
                        "ticker": pick.get("ticker"),
                        "name": pick.get("name"),
                        "change_pct": pick.get("change_pct"),
                        "source": pick.get("source", "auto"),
                        "title": pick.get("title", ""),
                        "description": pick.get("description", ""),
                        "headline": pick.get("headline", ""),
                        "catalyst": pick.get("catalyst", ""),
                        "thesis": pick.get("thesis", ""),
                        "overall_label": pick.get("overall_label", ""),
                        "topic_key": pick.get("topic_key"),
                    }, indent=2))
                print(f"  queued {sid}")
                auto_paths.append(script_path)

    if args.auto and args.max > 0:
        n = run_queue(
            max_n=args.max,
            loop=args.loop,
            poll_interval=args.poll_interval,
            skip_upload=args.no_upload,
            paths=auto_paths,
        )
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

    n = run_queue(max_n=args.max, loop=args.loop, poll_interval=args.poll_interval, skip_upload=args.no_upload)
    print(f"\nProcessed {n} script(s).")


if __name__ == "__main__":
    main()
