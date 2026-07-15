"""Whisper word-level transcription for subtitle timing."""
from __future__ import annotations

import json
import re
from pathlib import Path


def merge_numeric_fragments(words: list[dict]) -> list[dict]:
    """Rejoin decimals and percentages split by Whisper word timestamps."""
    merged: list[dict] = []
    for word in words:
        current = dict(word)
        if (
            merged
            and re.search(r"\d$", merged[-1]["word"])
            and re.match(r"^(?:[.,]\d|%)", current["word"])
        ):
            merged[-1]["word"] += current["word"]
            merged[-1]["end"] = current["end"]
        else:
            merged.append(current)
    return merged


def transcribe_words(video: Path) -> list[dict]:
    """Return [{word, start, end}, ...] using faster-whisper base model on CPU."""
    from faster_whisper import WhisperModel
    model = WhisperModel("base", device="cpu", compute_type="int8")
    segments, _info = model.transcribe(str(video), word_timestamps=True, language="en")
    out = []
    for seg in segments:
        if not seg.words:
            continue
        for w in seg.words:
            text = (w.word or "").strip()
            if not text:
                continue
            out.append({"word": text, "start": float(w.start), "end": float(w.end)})
    return out


def write_jsonl(words: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for w in words:
            f.write(json.dumps(w) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def cached(video: Path, cache_dir: Path) -> list[dict] | None:
    """Return cached words if the video file hasn't changed since caching."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / (video.stem + ".jsonl")
    if not cache.exists():
        return None
    if video.stat().st_mtime > cache.stat().st_mtime:
        return None
    return read_jsonl(cache)


def transcribe_with_cache(video: Path, cache_dir: Path) -> list[dict]:
    words = cached(video, cache_dir)
    if words is not None:
        return merge_numeric_fragments(words)
    words = merge_numeric_fragments(transcribe_words(video))
    write_jsonl(words, cache_dir / (video.stem + ".jsonl"))
    return words
