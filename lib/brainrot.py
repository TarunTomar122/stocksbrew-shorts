"""Brainrot short compositing: gameplay bg + speaker image + avatar audio + subtitles.

Supports both single-speaker and two-character dialogue modes.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from PIL import Image

from . import subtitles as subs
from . import components as comps
from .ffmpeg import probe, run

W, H = 1080, 1920  # 9:16 vertical

# Speaker image mapping — character name → image path relative to ROOT
SPEAKER_IMAGES = {
    "rae2": "assets/speaker/charimage.png",
    "rae": "assets/speaker/char2image.png",
}


def render_speaker(speaker: Path, frame_h: int, scale: float) -> Path:
    """Resize the speaker to `scale` of frame height. No crop, no circle. RGBA preserved."""
    img = Image.open(speaker).convert("RGBA")
    target_h = int(frame_h * scale)
    if img.height > target_h:
        ratio = target_h / img.height
        target_w = int(img.width * ratio)
        img = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
    out = Path(subprocess.check_output(["mktemp", "-u", "-t", "speaker"]).strip().decode() + ".png")
    img.save(out)
    return out


def _overlay_position(sp_w: int, sp_h: int, corner: str) -> tuple[int, int]:
    margin = 40
    if corner == "top-right":
        return W - sp_w - margin, margin
    elif corner == "top-left":
        return margin, margin
    elif corner == "bottom-right":
        return W - sp_w - margin, H - sp_h - margin
    else:
        return margin, H - sp_h - margin


def build(
    avatar_video: Path,
    gameplay: Path,
    speaker: Path | None,
    output: Path,
    duration: float,
    words: list[dict] | None = None,
    components: list[dict] | None = None,
    dialogue_lines: list[dict] | None = None,
    speaker_corner: str = "bottom-right",
    speaker_scale: float = 0.55,
    subtitle_margin: int = 320,
    subtitle_fontsize: int = 120,
) -> Path:
    """Compose a brainrot short.

    Args:
        avatar_video: MP4 with the talking avatar audio.
        gameplay:     MP4 looped as background.
        speaker:      Default speaker PNG (used when dialogue_lines is None).
        output:       Final MP4 path.
        duration:     Total duration in seconds.
        words:        Word-level timestamps [{word,start,end}] for subtitles.
        components:   Visual component cards [{type, show_at, data}].
        dialogue_lines: For two-character dialogue: [{character, text, start_time, end_time}].
        speaker_corner: default speaker position.
        speaker_scale: Speaker height as fraction of frame height.
        subtitle_margin: Top y-position for subtitles (px).
    """
    target = (W, H)

    # Pre-render speaker PNGs
    root = Path(__file__).resolve().parent.parent
    speaker_pngs: dict[str, Path] = {}  # character → temp PNG path
    for char, rel_path in SPEAKER_IMAGES.items():
        img_path = root / rel_path
        if img_path.exists():
            speaker_pngs[char] = render_speaker(img_path, H, speaker_scale)

    # Fallback single speaker
    default_png = None
    default_sx = default_sy = 0
    if speaker and speaker.exists():
        default_png = render_speaker(speaker, H, speaker_scale)
        sp_w, sp_h = probe(default_png)[:2]
        default_sx, default_sy = _overlay_position(sp_w, sp_h, speaker_corner)

    base = Path(subprocess.check_output(["mktemp", "-d"]).strip().decode())
    all_temp_pngs: list[Path] = list(speaker_pngs.values())
    if default_png:
        all_temp_pngs.append(default_png)
    component_pngs: list[Path] = []
    try:
        inputs = ["-stream_loop", "-1", "-i", str(gameplay)]
        filters = [
            f"[0:v]scale={target[0]}:{target[1]}:force_original_aspect_ratio=increase,"
            f"crop={target[0]}:{target[1]}[bg]"
        ]
        last = "bg"
        next_idx = 1

        # Speaker overlay — either dialogue mode or single-speaker mode
        if dialogue_lines:
            # Two-character dialogue: overlay each character's image during their speaking window
            for line in dialogue_lines:
                char = line.get("character", "rae2")
                start_t = float(line.get("start_time", 0))
                end_t = float(line.get("end_time", start_t + 3))
                png = speaker_pngs.get(char)
                if not png:
                    continue
                sp_w, sp_h = probe(png)[:2]
                sx, sy = _overlay_position(sp_w, sp_h, speaker_corner)
                inputs.extend(["-loop", "1", "-i", str(png)])
                filters.append(
                    f"[{last}][{next_idx}:v]overlay={sx}:{sy}:format=auto:"
                    f"enable='between(t,{start_t:.3f},{end_t:.3f})'[sp{next_idx}]"
                )
                last = f"sp{next_idx}"
                next_idx += 1
        elif default_png:
            # Single-speaker mode (backward compatible)
            inputs.extend(["-loop", "1", "-i", str(default_png)])
            filters.append(f"[{last}][{next_idx}:v]overlay={default_sx}:{default_sy}:format=auto[ov]")
            last = "ov"
            next_idx += 1

        # Component cards — render PNGs and overlay at timed intervals
        if components:
            for comp in components:
                png = comps.render_component(comp)
                if not png:
                    continue
                component_pngs.append(png)
                cx, cy = comps.card_position(png)
                show_at = float(comp.get("show_at", 0.3))
                start_t = max(0.0, show_at * duration)
                end_t = min(duration, start_t + 2.5)
                inputs.extend(["-loop", "1", "-i", str(png)])
                filters.append(
                    f"[{last}][{next_idx}:v]overlay={cx}:{cy}:format=auto:"
                    f"enable='between(t,{start_t:.3f},{end_t:.3f})'[c{next_idx}]"
                )
                last = f"c{next_idx}"
                next_idx += 1

        if words:
            chain = subs.build_chain(words, subtitle_margin, last, subtitle_fontsize)
            last = subs.last_label(words)
            filters[-1] = filters[-1] + "," + chain

        final_filter = ";".join(filters) + f";[{last}]format=yuv420p[vout]"

        video_only = base / "video.mp4"
        cmd = [
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", final_filter,
            "-map", "[vout]",
            "-t", f"{duration:.3f}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "20",
            "-r", "30",
            str(video_only),
        ]
        run(cmd)

        output.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_only),
            "-i", str(avatar_video),
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-shortest",
            str(output),
        ]
        run(cmd)
        return output
    finally:
        shutil.rmtree(base, ignore_errors=True)
        for png in all_temp_pngs + component_pngs:
            if png.exists():
                png.unlink()
