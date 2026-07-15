"""Build ffmpeg drawtext filter chains for karaoke-style one-word-at-a-time subtitles."""
from __future__ import annotations

from pathlib import Path

FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)


def find_font_path() -> str | None:
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            return p
    return None


def build_chain(words: list[dict], top_margin: int, last_label: str,
                fontsize: int = 120, color: str = "white",
                border_w: int = 6) -> str:
    """Build `[last]drawtext=...[s1],[s1]drawtext=...[s2],...` chain.

    Each drawtext shows one word with enable='between(t,start,end)'.
    """
    font_path = find_font_path()
    font_arg = f"fontfile='{font_path}':" if font_path else ""

    parts = []
    prev = last_label
    for i, w in enumerate(words):
        text = w["word"].replace("\\", "\\\\").replace("'", "").replace(":", "\\:")
        start = w["start"]
        end = w["end"]
        out = f"s{i+1}"
        parts.append(
            f"[{prev}]drawtext={font_arg}text='{text}':"
            f"expansion=none:"
            f"fontsize={fontsize}:fontcolor={color}:borderw={border_w}:bordercolor=black:"
            f"x=(w-text_w)/2:y={top_margin}:"
            f"enable='between(t,{start:.3f},{end:.3f})'"
            f"[{out}]"
        )
        prev = out
    return ",".join(parts)


def last_label(words: list[dict]) -> str:
    return f"s{len(words)}"
