"""Runway avatar video generation via the gwm1_avatars model."""
from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

import requests
from dotenv import load_dotenv
from runwayml import RunwayML

from .ffmpeg import probe, run

load_dotenv()

AVATAR_IDS = {
    "rae2": "a454af7d-49a2-4e09-b78f-7048b7466bdd",
    "rae": "ac213fea-3b90-4951-a25a-ecc5e8d9a055",
}


@dataclass
class AvatarResult:
    video_path: Path
    avatar_id: str
    duration: float


@dataclass
class DialogueLine:
    character: str
    text: str
    video_path: Path
    start_time: float
    end_time: float
    duration: float


@dataclass
class DialogueResult:
    video_path: Path
    duration: float
    lines: list[DialogueLine]


def _client() -> RunwayML:
    key = os.environ.get("RUNWAYML_API_SECRET")
    if not key:
        raise RuntimeError("RUNWAYML_API_SECRET not set in .env")
    return RunwayML(api_key=key)


def list_avatars() -> list[dict]:
    """List all avatars in the account. Returns [{id, name}, ...]."""
    client = _client()
    out = []
    for a in client.avatars.list(limit=100):
        out.append({"id": a.id, "name": a.name})
    return out


def resolve_avatar(name_or_id: str) -> str:
    """Accept a known name (rae2, rae) or a raw UUID."""
    return AVATAR_IDS.get(name_or_id, name_or_id)


def generate(text: str, avatar: str = "rae2", out_dir: Path | None = None) -> AvatarResult:
    """Generate a talking-avatar MP4 from script text. Returns the local file."""
    out_dir = out_dir or Path("output")
    out_dir.mkdir(parents=True, exist_ok=True)
    avatar_id = resolve_avatar(avatar)

    client = _client()
    task = client.avatar_videos.create(
        model="gwm1_avatars",
        avatar={"type": "custom", "avatar_id": avatar_id},
        speech={"type": "text", "text": text},
    )
    result = task.wait_for_task_output()
    if result.status != "SUCCEEDED":
        raise RuntimeError(f"Avatar generation failed: {result.status}")

    output = result.output
    if isinstance(output, list) and output:
        url = output[0]
    elif isinstance(output, dict):
        url = output.get("url") or output.get("video", {}).get("url")
    else:
        url = str(output)

    suffix = uuid.uuid4().hex[:8]
    out = out_dir / f"avatar-{avatar}-{suffix}.mp4"
    resp = requests.get(url)
    resp.raise_for_status()
    out.write_bytes(resp.content)

    _, _, duration = probe(out)
    return AvatarResult(video_path=out, avatar_id=avatar_id, duration=duration)


def generate_dialogue(dialogue: list[dict], out_dir: Path | None = None) -> DialogueResult:
    """Generate a multi-character dialogue video.

    Each dialogue entry: {"character": "rae2"|"rae", "text": "..."}.
    Generates one avatar video per line, concatenates them, and returns
    timing info for each line (for speaker overlay switching).
    """
    out_dir = out_dir or Path("output")
    out_dir.mkdir(parents=True, exist_ok=True)

    tmp = Path(tempfile.mkdtemp(prefix="dialogue-"))
    line_videos: list[Path] = []
    line_results: list[DialogueLine] = []

    try:
        # Generate each line
        for i, line in enumerate(dialogue):
            character = line.get("character", "rae2")
            text = line.get("text", "")
            if not text:
                continue
            print(f"    line {i+1}/{len(dialogue)}: {character} — {text[:50]}...")
            result = generate(text, avatar=character, out_dir=tmp)
            line_videos.append(result.video_path)

        if not line_videos:
            raise RuntimeError("No dialogue lines to generate")

        # Concatenate all line videos
        suffix = uuid.uuid4().hex[:8]
        combined = out_dir / f"dialogue-{suffix}.mp4"

        if len(line_videos) == 1:
            shutil.copy(line_videos[0], combined)
        else:
            # Use ffmpeg concat
            list_file = tmp / "concat.txt"
            list_file.write_text("\n".join(f"file '{v.resolve()}'" for v in line_videos))
            run([
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", str(list_file),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast",
                str(combined),
            ])

        # Calculate timing for each line
        current_time = 0.0
        for i, (line, video) in enumerate(zip(dialogue, line_videos)):
            _, _, dur = probe(video)
            line_results.append(DialogueLine(
                character=line.get("character", "rae2"),
                text=line.get("text", ""),
                video_path=video,
                start_time=current_time,
                end_time=current_time + dur,
                duration=dur,
            ))
            current_time += dur

        _, _, total_duration = probe(combined)
        return DialogueResult(
            video_path=combined,
            duration=total_duration,
            lines=line_results,
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
