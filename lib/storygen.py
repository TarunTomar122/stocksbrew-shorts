"""Generate viral finance shorts scripts as two-character dialogue via OpenAI.

CHARACTERS:
- rae2 (Peter-type): Blunt, casual, sets up the topic. Says things like "Hey
  you see what Nvidia did today?" or "Bro this stock just tanked".
- rae (Stewie-type): Clever, sarcastic, delivers the insight. Says things
  like "Ugh, please. Everyone's obsessed with Nvidia but nobody's watching
  Broadcom" or "Oh please, this dip is a gift wrapped in red ink."

Each script is a 2-4 line dialogue between them. Total 30-45 words across
all lines combined.

KEY RULE: scripts use COMPANY NAMES, never ticker symbols (Runway can't
pronounce "AMAT" — use "Applied Materials" instead).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / ".cache" / "stories"

load_dotenv(ROOT / ".env")

SYSTEM_PROMPT = """You write 30-45 word DIALOGUE scripts for viral finance shorts (TikTok/YouTube Shorts), PLUS choose visual component cards to pop up during the video.

Two characters talk to each other about a stock story:
- rae2: Blunt, casual, sets up the topic. Like a friend who just saw something wild and needs to share it. "Hey you see what Nvidia did today?" / "Bro this stock just tanked".
- rae: Clever, sarcastic, delivers the insight. Knows more than rae2 and loves showing it. "Ugh, please. Everyone's obsessed with Nvidia but nobody watching Broadcom." / "Oh please, this dip is a gift wrapped in red ink."

ABSOLUTE RULES FOR DIALOGUE:
1. Use the COMPANY NAME, never the ticker symbol. "Nvidia" not "NVDA".
2. Tell a STORY through the conversation. rae2 sets up, rae delivers the punch.
3. 2-4 lines total, alternating between rae2 and rae. Each line is 8-20 words.
4. 30-45 words TOTAL across all lines combined.
5. Sound like two friends talking — casual, funny, opinionated.
6. At most ONE number across all lines (e.g. "dropped 13 percent"). Zero is fine.
7. BANNED PHRASES — never use any of these: "reported earnings", "beating estimates", "EPS", "RSI", "overbought", "overheated", "valuation", "catalyst", "thesis", "is on fire", "heating up", "here's the kicker", "here's the twist", "here's the deal", "here's the scoop", "hold up", "interesting times", "stay tuned", "we'll see", "let's see", "don't be fooled", "the real question is", "crucial moment", "buckle up", "for the ride", "wishful thinking", "putting them to the test", "riding the wave", "shine is fading".
8. The LAST line should feel like a mic drop — a punchy observation, not a question or teaser.
9. VARY the dynamic: sometimes rae2 is the one who knows, sometimes rae is surprised. Don't always have the same pattern.

COMPONENT CARDS:
Pick 1-2 visual cards to show during the video. Each appears in the upper half of the screen for ~2.5 seconds. Available types:

- big_move: Shows the stock's % move huge. Data: {"pct": number, "direction": "up"/"down", "name": "Company Name"}
- company_card: Shows who the company is. Data: {"name": "Company Name", "sector": "Technology"}
- context_quote: A pull-quote from the story. Data: {"text": "short punchy quote", "source": ""}
- verdict_stamp: Market read stamp. Data: {"label": "bullish"/"bearish"/"mixed"/"growth"}. Match to the actual story.
- reddit_buzz: Reddit activity. Data: {"posts": number, "level": "high"/"medium"/"low"}. Only use if reddit_posts > 0.

COMPONENT RULES:
- Pick 1-2 components that enhance the story. Don't force both.
- show_at is a fraction (0.0-1.0) of when in the video to show the card.
- Space components out. big_move early, verdict_stamp late.
- reddit_buzz only if reddit_posts > 0.

OUTPUT FORMAT — return valid JSON only, no markdown, no code fences:
{
  "dialogue": [{"character": "rae2", "text": "..."}, {"character": "rae", "text": "..."}],
  "components": [...],
  "title": "Short catchy title (max 60 chars)",
  "description": "Engaging description with hashtags (max 200 chars)"
}

TITLE RULES:
- Max 60 characters
- Catchy, clickbait-y, makes people want to watch
- Include the company name
- Examples: "Oracle Just Tanked 13% — Here's Why It's a Gift", "Nobody's Watching Broadcom", "Cloudflare Crashed 23% — Falling Knife or Screaming Buy?"

DESCRIPTION RULES:
- Max 200 characters
- Include company name and key insight
- Add hashtags at the end: #stocks #investing #shorts #stocksbrew
- Examples: "Oracle crashed after earnings but cloud revenue hit records. Is this dip a gift? #stocks #investing #shorts #stocksbrew" """

FEW_SHOT = [
    {
        "user": "Company: Oracle. Move: -13%. Context: Stock crashed after earnings but cloud revenue hit a record high. The CEO is betting everything on AI infrastructure. Sector: Technology. Verdict: growth.",
        "assistant": '{"dialogue": [{"character": "rae2", "text": "Bro Oracle just tanked 13 percent after earnings. That\\u2019s brutal."}, {"character": "rae", "text": "Oh please. Their cloud revenue just hit a record and Larry Ellison is literally betting the company on AI."}, {"character": "rae2", "text": "So you\\u2019re saying buy the dip?"}, {"character": "rae", "text": "I\\u2019m saying this dip is a gift wrapped in red ink."}], "components": [{"type": "big_move", "show_at": 0.05, "data": {"pct": -13.0, "direction": "down", "name": "Oracle"}}, {"type": "context_quote", "show_at": 0.5, "data": {"text": "Cloud revenue hit a new record high", "source": "earnings"}}, {"type": "verdict_stamp", "show_at": 0.85, "data": {"label": "growth"}}], "title": "Oracle Tanked 13% — But Here's Why It's a Gift", "description": "Oracle crashed after earnings but cloud revenue just hit a record. Is this dip a gift? #stocks #investing #shorts #stocksbrew"}',
    },
    {
        "user": "Company: Cloudflare. Move: -23%. Context: Company slashed 20 percent of workforce and gave weak guidance. Reddit is buzzing with 140 posts. Sector: Technology. Verdict: bearish.",
        "assistant": '{"dialogue": [{"character": "rae2", "text": "Yo Cloudflare just crashed 23 percent. They fired a fifth of the company."}, {"character": "rae", "text": "And the guidance was absolutely brutal. But here\\u2019s the thing \\u2014 they\\u2019re still the backbone of half the internet."}, {"character": "rae2", "text": "So falling knife or screaming buy?"}, {"character": "rae", "text": "That\\u2019s the million dollar question nobody wants to answer."}], "components": [{"type": "big_move", "show_at": 0.05, "data": {"pct": -23.0, "direction": "down", "name": "Cloudflare"}}, {"type": "reddit_buzz", "show_at": 0.4, "data": {"posts": 140, "level": "high"}}, {"type": "verdict_stamp", "show_at": 0.85, "data": {"label": "bearish"}}], "title": "Cloudflare Crashed 23% — Falling Knife or Buy?", "description": "Cloudflare fired 20% of their workforce and crashed. Reddit is buzzing. Falling knife or screaming buy? #stocks #investing #shorts #stocksbrew"}',
    },
    {
        "user": "Company: Broadcom. Move: +1.4%. Context: Everyone focused on Nvidia but Broadcom quietly raised guidance 50 percent. Stock barely moved. They dominate the networking chip layer. Sector: Technology. Verdict: bullish.",
        "assistant": '{"dialogue": [{"character": "rae2", "text": "Everyone keeps talking about Nvidia but what about Broadcom?"}, {"character": "rae", "text": "Broadcom just raised guidance 50 percent and nobody noticed. They\\u2019re quietly eating the entire networking layer."}, {"character": "rae2", "text": "And the stock barely moved?"}, {"character": "rae", "text": "Exactly. That\\u2019s why it\\u2019s the most interesting name in the market right now."}], "components": [{"type": "company_card", "show_at": 0.1, "data": {"name": "Broadcom", "sector": "Semiconductors"}}, {"type": "verdict_stamp", "show_at": 0.8, "data": {"label": "bullish"}}], "title": "Nobody\\u2019s Watching Broadcom — Here\\u2019s Why They Should", "description": "Broadcom raised guidance 50% and nobody noticed. They\\u2019re eating the networking layer. #stocks #investing #shorts #stocksbrew"}',
    },
]


def _client():
    from openai import OpenAI
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY not set in .env")
    return OpenAI(api_key=key)


def _cache_key(pick: dict) -> str:
    raw = json.dumps(pick, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _read_cache(key: str) -> str | None:
    """Returns cached JSON string or None."""
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    return path.read_text()


def _write_cache(key: str, pick: dict, result_json: str) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{key}.json").write_text(result_json)


def _format_pick(pick: dict) -> str:
    """Build the user message from a story pick. Emphasizes company name + narrative."""
    name = pick.get("name") or pick.get("ticker", "this company")
    lines = [f"Company: {name}"]

    pct = pick.get("change_pct")
    if pct is not None:
        direction = "up" if float(pct) >= 0 else "down"
        lines.append(f"Move: {direction} {abs(float(pct)):.1f}%")

    if pick.get("headline"):
        lines.append(f"What happened: {pick['headline']}")

    if pick.get("catalyst"):
        lines.append(f"Why: {pick['catalyst']}")

    if pick.get("thesis"):
        lines.append(f"Angle: {pick['thesis']}")

    if pick.get("reddit_posts"):
        lines.append(f"Reddit buzz: {pick['reddit_posts']} posts")
        discussions = pick.get("reddit_discussions") or []
        if discussions:
            lines.append(f"Reddit talk: {str(discussions[0])[:150]}")

    if pick.get("sector"):
        lines.append(f"Sector: {pick['sector']}")

    return "\n".join(lines)


def generate_script(pick: dict, *, model: str = "gpt-4o-mini") -> dict:
    """Generate a dialogue script + component cards for one story pick.

    Returns: {"dialogue": [{"character": str, "text": str}, ...], "components": [...], ...pick_fields}
    """
    key = _cache_key(pick)
    cached = _read_cache(key)
    if cached:
        return json.loads(cached)

    client = _client()
    user_msg = _format_pick(pick)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for shot in FEW_SHOT:
        messages.append({"role": "user", "content": shot["user"]})
        messages.append({"role": "assistant", "content": shot["assistant"]})
    messages.append({"role": "user", "content": user_msg})

    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=400,
        temperature=0.9,
        response_format={"type": "json_object"},
    )
    raw = (resp.choices[0].message.content or "").strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: wrap as single rae2 line
        parsed = {"dialogue": [{"character": "rae2", "text": raw.strip().strip('"')}], "components": []}

    dialogue = parsed.get("dialogue", [])
    components = parsed.get("components", [])

    # Validate dialogue
    if not dialogue:
        dialogue = [{"character": "rae2", "text": _fallback_script(pick)}]

    # Total word count guard
    total_words = sum(len(line.get("text", "").split()) for line in dialogue)
    if total_words > 60:
        # Trim last line
        last = dialogue[-1].get("text", "")
        words = last.split()
        dialogue[-1]["text"] = " ".join(words[:12]).rstrip(",.") + "."

    result = {**pick, "dialogue": dialogue, "components": components}

    _write_cache(key, pick, json.dumps(result))
    return result


def generate_scripts(picks: list[dict], *, model: str = "gpt-4o-mini") -> list[dict]:
    """Generate dialogue scripts + components for many picks, preserving order."""
    out = []
    for i, pick in enumerate(picks, 1):
        try:
            result = generate_script(pick, model=model)
            total_words = sum(len(l.get("text", "").split()) for l in result.get("dialogue", []))
            nc = len(result.get("components", []))
            lines = len(result.get("dialogue", []))
            preview = result["dialogue"][0]["text"][:50] if result.get("dialogue") else ""
            print(f"  [{i}/{len(picks)}] {pick.get('name', pick.get('ticker', '?'))} ({total_words}w, {lines} lines, {nc} cards): {preview}...")
            out.append(result)
        except Exception as e:
            print(f"  [{i}/{len(picks)}] {pick.get('name', pick.get('ticker', '?'))}: FAILED ({e})")
            out.append({**pick, "dialogue": [{"character": "rae2", "text": _fallback_script(pick)}], "components": []})
    return out


def _fallback_script(pick: dict) -> str:
    """If OpenAI fails, produce a deterministic but still usable script."""
    name = pick.get("name") or pick.get("ticker", "this stock")
    pct = pick.get("change_pct")
    if pct is None:
        return f"Hey you seen what {name} is doing today? Most people haven't noticed yet."
    direction = "ripped higher" if float(pct) >= 0 else "tanked"
    return f"Hey {name} just {direction} and most people haven't noticed yet."
