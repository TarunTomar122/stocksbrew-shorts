"""Render 5 plug-and-play component cards as transparent PNGs.

Each card is designed for the upper half of a 1080x1920 vertical short,
positioned below subtitles (y=320) and above the speaker (bottom-right).
Cards are ~900px wide, variable height, centered horizontally.

Component types:
  big_move       — huge % change with arrow, green/red
  company_card   — company name + sector + one-liner
  context_quote  — pull-quote from headline/thesis
  verdict_stamp  — BULLISH / BEARISH / NEUTRAL stamp
  reddit_buzz    — post count + trending indicator
"""
from __future__ import annotations

import math
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

CARD_W = 900
CARD_X = 90  # (1080 - 900) / 2
CARD_Y = 620  # top position, well below subtitles

# Colors
BG_DARK = (10, 18, 32, 235)
BG_GLASS = (15, 23, 42, 210)
WHITE = (255, 255, 255, 255)
MUTED = (148, 163, 184, 255)
GREEN = (34, 197, 94, 255)
RED = (248, 113, 113, 255)
ACCENT_BLUE = (59, 130, 246, 255)
REDDIT_ORANGE = (255, 69, 0, 255)
GOLD = (251, 191, 36, 255)


def _font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for p in candidates:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _rounded_card(w: int, h: int, bg=BG_DARK, radius=32, border=None) -> Image.Image:
    """Create a solid rounded-rect card with optional border."""
    pad = 20
    canvas = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    # Solid card body
    draw.rounded_rectangle((pad, pad, pad + w, pad + h), radius=radius, fill=bg)

    # Border
    if border:
        draw.rounded_rectangle((pad, pad, pad + w, pad + h), radius=radius, outline=border, width=4)

    return canvas


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Word-wrap text to fit within max_width pixels."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = (current + " " + word).strip()
        bbox = font.getbbox(test)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _temp_path(prefix: str) -> Path:
    return Path(subprocess.check_output(["mktemp", "-u", "-t", prefix]).strip().decode() + ".png")


def render_big_move(data: dict) -> Path:
    """Huge % change card. Green if up, red if down. No arrow."""
    pct = float(data.get("pct", 0))
    name = data.get("name", "")
    is_up = pct >= 0
    color = GREEN if is_up else RED
    sign = "+" if is_up else ""

    h = 280
    card = _rounded_card(CARD_W, h, bg=BG_DARK, radius=36, border=color)
    draw = ImageDraw.Draw(card)
    pad = 20

    cx = CARD_W // 2 + pad
    cy = h // 2 + pad

    pct_font = _font(160, bold=True)
    pct_text = f"{sign}{pct:.1f}%"
    draw.text((cx, cy), pct_text, font=pct_font, fill=color, anchor="mm")

    if name:
        name_font = _font(40, bold=True)
        draw.text((cx, 50 + pad), name, font=name_font, fill=WHITE, anchor="mm")

    out = _temp_path("comp_bigmov")
    card.save(out)
    return out


def render_company_card(data: dict) -> Path:
    """Company name + sector only. Big and bold."""
    name = data.get("name", "Unknown")
    sector = data.get("sector", "")

    h = 240
    card = _rounded_card(CARD_W, h, bg=BG_DARK, radius=36, border=ACCENT_BLUE)
    draw = ImageDraw.Draw(card)
    pad = 20

    cx = CARD_W // 2 + pad
    cy = h // 2 + pad

    name_font = _font(80, bold=True)
    draw.text((cx, cy - 30), name, font=name_font, fill=WHITE, anchor="mm")

    if sector:
        sector_font = _font(40, bold=True)
        draw.text((cx, cy + 50), sector.upper(), font=sector_font, fill=ACCENT_BLUE, anchor="mm")

    out = _temp_path("comp_company")
    card.save(out)
    return out


def render_context_quote(data: dict) -> Path:
    """Pull-quote card. Big text, minimal."""
    text = data.get("text", "")
    source = data.get("source", "")

    quote_font = _font(52, bold=True)
    source_font = _font(32, bold=False)
    max_width = CARD_W - 160

    lines = _wrap_text(text, quote_font, max_width)[:3]

    h = 100 + len(lines) * 68 + (50 if source else 20)
    card = _rounded_card(CARD_W, h, bg=BG_DARK, radius=36, border=ACCENT_BLUE)
    draw = ImageDraw.Draw(card)
    pad = 20

    cx = CARD_W // 2 + pad
    for i, line in enumerate(lines):
        draw.text((cx, 80 + pad + i * 68), line, font=quote_font, fill=WHITE, anchor="mm")

    if source:
        draw.text((cx, h - 40 + pad), f"— {source}", font=source_font, fill=MUTED, anchor="mm")

    out = _temp_path("comp_quote")
    card.save(out)
    return out


def render_verdict_stamp(data: dict) -> Path:
    """Bold BULLISH / BEARISH / NEUTRAL stamp."""
    label = str(data.get("label", "neutral")).lower()
    labels_map = {
        "bullish": ("BULLISH", GREEN),
        "bearish": ("BEARISH", RED),
        "growth": ("GROWTH", GREEN),
        "value": ("VALUE", ACCENT_BLUE),
        "neutral": ("NEUTRAL", MUTED),
        "mixed": ("MIXED", GOLD),
    }
    display, color = labels_map.get(label, ("NEUTRAL", MUTED))

    h = 260
    card = _rounded_card(CARD_W, h, bg=BG_DARK, radius=36, border=color)
    draw = ImageDraw.Draw(card)
    pad = 20

    # Inner stamp border
    inner_pad = 24
    draw.rounded_rectangle(
        (pad + inner_pad, pad + inner_pad, pad + CARD_W - inner_pad, pad + h - inner_pad),
        radius=24, outline=color, width=6
    )

    cx = CARD_W // 2 + pad
    cy = h // 2 + pad

    label_font = _font(100, bold=True)
    draw.text((cx, cy), display, font=label_font, fill=color, anchor="mm")

    out = _temp_path("comp_verdict")
    card.save(out)
    return out


def render_reddit_buzz(data: dict) -> Path:
    """Reddit buzz card with post count and trending bar."""
    posts = int(data.get("posts", 0))
    level = data.get("level", "medium")

    level_colors = {"high": RED, "medium": GOLD, "low": MUTED}
    level_color = level_colors.get(level, GOLD)

    h = 260
    card = _rounded_card(CARD_W, h, bg=BG_DARK, radius=36, border=REDDIT_ORANGE)
    draw = ImageDraw.Draw(card)
    pad = 20

    cx = CARD_W // 2 + pad
    cy = h // 2 + pad

    # Label
    label_font = _font(36, bold=True)
    draw.text((cx, 50 + pad), "TRENDING ON REDDIT", font=label_font, fill=REDDIT_ORANGE, anchor="mm")

    # Post count
    count_font = _font(100, bold=True)
    draw.text((cx, cy), f"{posts}", font=count_font, fill=WHITE, anchor="mm")

    # Posts label
    posts_font = _font(34, bold=True)
    draw.text((cx, cy + 70), "POSTS", font=posts_font, fill=MUTED, anchor="mm")

    out = _temp_path("comp_reddit")
    card.save(out)
    return out


RENDERERS = {
    "big_move": render_big_move,
    "company_card": render_company_card,
    "context_quote": render_context_quote,
    "verdict_stamp": render_verdict_stamp,
    "reddit_buzz": render_reddit_buzz,
}


def render_component(comp: dict) -> Path | None:
    """Render a single component dict to a PNG path. Returns None if unknown type."""
    ctype = comp.get("type", "")
    renderer = RENDERERS.get(ctype)
    if not renderer:
        return None
    data = comp.get("data", {})
    return renderer(data)


def render_all(components: list[dict]) -> list[tuple[dict, Path]]:
    """Render all components. Returns [(component_dict, png_path), ...]."""
    out = []
    for comp in components:
        png = render_component(comp)
        if png:
            out.append((comp, png))
    return out


def card_position(png_path: Path) -> tuple[int, int]:
    """Return (x, y) overlay position for a component PNG.
    Centered horizontally, in the upper half below subtitles."""
    img = Image.open(png_path)
    w = img.width
    x = (1080 - w) // 2
    y = CARD_Y
    return x, y
