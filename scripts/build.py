#!/usr/bin/env python3
"""
One-off CLI: avatar, brainrot, clip subcommands.

  python scripts/build.py avatar --text "..." --avatar rae2
  python scripts/build.py brainrot --avatar-video output/avatar-x.mp4 --gameplay assets/gameplay/randombg_01_26s.mp4
  python scripts/build.py clip --source brainrot2.mp4 --count 20
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib import avatar, brainrot, clipper, transcribe


def cmd_avatar(args) -> None:
    result = avatar.generate(args.text, avatar=args.avatar)
    print(f"Avatar: {result.video_path} ({result.duration:.1f}s)")
    if args.brainrot:
        print("Auto-composing brainrot (random gameplay)...")
        from lib import catalog
        gp = catalog.pick("gameplay", tags=["brainrot"])
        gp_path = catalog.resolve_path(gp)
        speaker = ROOT / "assets" / "speaker" / "charimage.png"
        words = transcribe.transcribe_with_cache(result.video_path, ROOT / ".cache" / "transcripts")
        out = Path(args.output) if args.output else result.video_path.with_name(f"brainrot-{result.video_path.stem}.mp4")
        brainrot.build(
            avatar_video=result.video_path,
            gameplay=gp_path,
            speaker=speaker if speaker.exists() else None,
            output=out,
            duration=result.duration,
            words=words,
        )
        print(f"Brainrot: {out}")


def cmd_brainrot(args) -> None:
    speaker = Path(args.speaker) if args.speaker else None
    if speaker and not speaker.is_absolute():
        speaker = ROOT / speaker
    gameplay = Path(args.gameplay)
    if not gameplay.is_absolute():
        gameplay = ROOT / gameplay
    avatar_v = Path(args.avatar_video)
    if not avatar_v.is_absolute():
        avatar_v = ROOT / avatar_v

    words = None
    if args.subtitles:
        words = transcribe.transcribe_with_cache(avatar_v, ROOT / ".cache" / "transcripts")
        print(f"Loaded {len(words)} words")

    out = Path(args.output) if args.output else ROOT / "output" / "brainrot" / f"{avatar_v.stem}-brainrot.mp4"
    if not out.is_absolute():
        out = ROOT / out

    brainrot.build(
        avatar_video=avatar_v,
        gameplay=gameplay,
        speaker=speaker if speaker and speaker.exists() else None,
        output=out,
        duration=args.duration or 0,
        words=words,
        speaker_corner=args.speaker_corner,
        speaker_scale=args.speaker_scale,
        subtitle_margin=args.subtitle_margin,
    )
    print(f"Brainrot: {out}")


def cmd_clip(args) -> None:
    src = Path(args.source)
    if not src.is_absolute():
        src = ROOT / src
    out_dir = ROOT / "assets" / "gameplay"
    items = clipper.sample_clips(
        source=src,
        out_dir=out_dir,
        count=args.count,
        min_duration=args.min_duration,
        max_duration=args.max_duration,
        seed=args.seed,
    )
    clipper.update_catalog(items, ROOT / "catalog" / "gameplay.json")
    print(f"\n{len(items)} clips in {out_dir} (indexed in catalog/gameplay.json)")


def main() -> None:
    p = argparse.ArgumentParser(description="One-off CLI for the brainrot pipeline.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("avatar", help="Generate a Runway avatar video")
    pa.add_argument("--text", required=True)
    pa.add_argument("--avatar", default="rae2")
    pa.add_argument("--brainrot", action="store_true", help="Auto-compose brainrot after")
    pa.add_argument("--output", help="Output path for brainrot if --brainrot")
    pa.set_defaults(func=cmd_avatar)

    pb = sub.add_parser("brainrot", help="Compose a brainrot short from existing avatar video")
    pb.add_argument("--avatar-video", required=True)
    pb.add_argument("--gameplay", required=True)
    pb.add_argument("--speaker")
    pb.add_argument("--output")
    pb.add_argument("--duration", type=float)
    pb.add_argument("--subtitles", action="store_true")
    pb.add_argument("--speaker-corner", default="bottom-right",
                    choices=("top-left", "top-right", "bottom-left", "bottom-right"))
    pb.add_argument("--speaker-scale", type=float, default=0.55)
    pb.add_argument("--subtitle-margin", type=int, default=320)
    pb.set_defaults(func=cmd_brainrot)

    pc = sub.add_parser("clip", help="Re-sample brainrot clips from a source mp4")
    pc.add_argument("--source", required=True)
    pc.add_argument("--count", type=int, default=20)
    pc.add_argument("--min-duration", type=float, default=20)
    pc.add_argument("--max-duration", type=float, default=40)
    pc.add_argument("--seed", type=int)
    pc.set_defaults(func=cmd_clip)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
