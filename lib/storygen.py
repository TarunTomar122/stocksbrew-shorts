"""Generate viral finance shorts scripts as two-character dialogue via OpenAI.

CHARACTERS:
- rae2 (Peter-type): Blunt, casual, sets up the topic. Says things like "Hey
  you see what Nvidia did today?" or "Bro this stock just tanked".
- rae (Stewie-type): Clever, sarcastic, delivers the insight. Says things
  like "Ugh, please. Everyone's obsessed with Nvidia but nobody's watching
  Broadcom" or "Oh please, this dip is a gift wrapped in red ink."

Each script is a short, natural conversation with uneven turns. One character
can ask a quick question and the other can give a longer explanation.

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

SYSTEM_PROMPT = """You write natural 35-60 word conversations for finance shorts.

Two characters talk to each other about a stock story:
- rae2: Blunt, casual, sets up the topic. Like a friend who just saw something wild and needs to share it. "Hey you see what Nvidia did today?" / "Bro this stock just tanked".
- rae: Clever, sarcastic, delivers the insight. Knows more than rae2 and loves showing it. "Ugh, please. Everyone's obsessed with Nvidia but nobody watching Broadcom." / "Oh please, this dip is a gift wrapped in red ink."

GOAL:
- Entertain while teaching one useful investor insight.
- Explain why the stock moved, the business mechanism behind it, and what still needs to be proven.

ABSOLUTE RULES:
1. Use the COMPANY NAME, never the ticker symbol. "Nvidia" not "NVDA".
2. Write 2-5 alternating turns with UNEVEN lengths. At least one turn must be a substantial 2-3 sentence explanation and at least one must be a short reaction.
3. Every reply must react to the previous line. Do not write alternating mini-monologues.
4. Mid-conversation questions are welcome, but the final line must be a declarative takeaway.
5. Sound like two smart friends talking — casual, funny, opinionated, and specific.
6. At most ONE number across the whole conversation. Zero is fine.
7. BANNED PHRASES — never use any of these: "reported earnings", "beating estimates", "EPS", "RSI", "overbought", "overheated", "valuation", "catalyst", "thesis", "is on fire", "heating up", "here's the kicker", "here's the twist", "here's the deal", "here's the scoop", "hold up", "interesting times", "stay tuned", "we'll see", "let's see", "don't be fooled", "the real question is", "crucial moment", "buckle up", "for the ride", "wishful thinking", "putting them to the test", "riding the wave", "shine is fading".
8. VARY the structure and dynamic. Either character may open, explain, misunderstand, or land the final line.
9. Never tell viewers to buy, sell, or hold.
10. Never write four similarly sized one-sentence turns. Do not begin a reply with empty agreement such as "Exactly", "Yeah", "You bet", "Right", or "Totally".

FINAL CHECK: silently rewrite the conversation if it is symmetrical, contains a banned phrase, ends with a question or hedge, or lacks one concrete business insight.

OUTPUT FORMAT — return valid JSON only, no markdown, no code fences:
{
  "dialogue": [{"character": "rae2", "text": "..."}, {"character": "rae", "text": "..."}],
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
        "user": "Company: Oracle. Move: down sharply. Context: The quarter disappointed traders, but cloud revenue hit a record and the company is spending heavily on AI infrastructure.",
        "assistant": """{"dialogue": [{"character": "rae2", "text": "Oracle fell hard. Is the cloud story actually breaking?"}, {"character": "rae", "text": "Not necessarily. The quarter disappointed traders, but cloud revenue still hit a record. The risk is whether all that AI infrastructure spending turns into profitable growth."}, {"character": "rae2", "text": "So Wall Street punished the bill before seeing what it bought."}, {"character": "rae", "text": "Now the cloud business has to earn its price tag."}], "title": "Oracle's Cloud Story Has Something to Prove", "description": "Oracle's cloud revenue is growing, but its AI spending now needs to produce real profits. #stocks #investing #shorts #stocksbrew"}""",
    },
    {
        "user": "Company: Cloudflare. Context: The company cut a fifth of its workforce and issued weak guidance, but its network remains widely used.",
        "assistant": """{"dialogue": [{"character": "rae", "text": "Cloudflare cut a fifth of its workforce and gave investors weak guidance."}, {"character": "rae2", "text": "That sounds less like efficiency and more like management pulling the fire alarm."}, {"character": "rae", "text": "Maybe. The network is still valuable, but the business must prove those cuts protect margins without choking growth."}], "title": "Cloudflare's Cuts Come With a Cost", "description": "Cloudflare is cutting deeply. Now it must protect margins without weakening future growth. #stocks #investing #shorts #stocksbrew"}""",
    },
]

_BANNED_OUTPUT = (
    "secret sauce",
    "we'll see",
    "we will see",
    "you bet",
    "exactly",
    "game changer",
    "what's next",
    "just hype",
)


def dialogue_issues(dialogue: list[dict]) -> list[str]:
    """Return concrete reasons a generated conversation should be rejected."""
    issues: list[str] = []
    text = " ".join(str(line.get("text", "")) for line in dialogue).lower()
    lengths = [len(str(line.get("text", "")).split()) for line in dialogue]

    if not 2 <= len(dialogue) <= 5:
        issues.append("use 2-5 dialogue turns")
    if any(line.get("character") not in {"rae", "rae2"} for line in dialogue):
        issues.append("use only rae and rae2")
    if dialogue and str(dialogue[-1].get("text", "")).rstrip().endswith("?"):
        issues.append("end with a declarative takeaway")
    if lengths and (max(lengths) < 18 or min(lengths) > 12):
        issues.append("use uneven turns with one substantial explanation and one short reaction")
    for phrase in _BANNED_OUTPUT:
        if phrase in text:
            issues.append(f"remove banned phrase: {phrase}")
    return issues


def _client():
    from openai import OpenAI
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY not set in .env")
    return OpenAI(api_key=key)


def _cache_key(pick: dict, model: str) -> str:
    raw = json.dumps({"model": model, "prompt": SYSTEM_PROMPT, "pick": pick}, sort_keys=True, default=str)
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


def generate_script(pick: dict, *, model: str = "gpt-4.1-mini") -> dict:
    """Generate a dialogue script + component cards for one story pick.

    Returns: {"dialogue": [{"character": str, "text": str}, ...], "components": [...], ...pick_fields}
    """
    key = _cache_key(pick, model)
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

    parsed = None
    for attempt in range(2):
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=400,
            temperature=0.7 if attempt == 0 else 0.4,
            response_format={"type": "json_object"},
        )
        raw = (resp.choices[0].message.content or "").strip()
        try:
            candidate = json.loads(raw)
        except json.JSONDecodeError:
            candidate = {}

        issues = dialogue_issues(candidate.get("dialogue") or [])
        if not issues:
            parsed = candidate
            break
        messages.extend([
            {"role": "assistant", "content": raw},
            {"role": "user", "content": "Rejected: " + "; ".join(issues) + ". Rewrite the complete JSON."},
        ])

    if parsed is None:
        raise ValueError("generated dialogue failed quality checks")

    dialogue = parsed.get("dialogue", [])
    title = parsed.get("title", "")
    description = parsed.get("description", "")

    result = {**pick, "dialogue": dialogue, "title": title, "description": description}

    _write_cache(key, pick, json.dumps(result))
    return result


def generate_scripts(picks: list[dict], *, model: str = "gpt-4.1-mini") -> list[dict]:
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
    return out


def _fallback_script(pick: dict) -> str:
    """If OpenAI fails, produce a deterministic but still usable script."""
    name = pick.get("name") or pick.get("ticker", "this stock")
    pct = pick.get("change_pct")
    if pct is None:
        return f"Hey you seen what {name} is doing today? Most people haven't noticed yet."
    direction = "ripped higher" if float(pct) >= 0 else "tanked"
    return f"Hey {name} just {direction} and most people haven't noticed yet."
