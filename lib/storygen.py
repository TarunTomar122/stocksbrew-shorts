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
import re
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
_INVESTMENT_ADVICE = re.compile(r"\b(?:buy(?:ing)?|sell(?:ing)?|hold)\b", re.I)
_LEGAL_NAME_WORDS = {"the", "inc", "corp", "corporation", "company", "class"}
_NUMBER_MENTION = re.compile(
    r"(?<!\w)\$?\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?(?:%|[KMBX])?",
    re.I,
)
_CONTRADICTION = re.compile(
    r"\b(?:despite|but|yet|although|while|even\s+(?:after|though|with)|"
    r"can't|cannot|couldn't|fails?\s+to)\b",
    re.I,
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


def experiment_issues(candidate: dict, pick: dict) -> list[str]:
    variant = pick.get("format_variant")
    issues = []
    full_output = json.dumps(candidate).lower()
    title = str(candidate.get("title") or "")
    description = str(candidate.get("description") or "")
    name = str(pick.get("name") or pick.get("ticker") or "").strip()
    name_words = [
        word.lower()
        for word in re.findall(r"[A-Za-z0-9]+", name)
        if word.lower() not in _LEGAL_NAME_WORDS
    ]
    if not title or len(title) > 60:
        issues.append("use a non-empty title no longer than 60 characters")
    if not description or len(description) > 200:
        issues.append("use a non-empty description no longer than 200 characters")
    if name_words and not any(word in title.lower() for word in name_words):
        issues.append("name the company in the title")
    if _INVESTMENT_ADVICE.search(full_output):
        issues.append("remove investment recommendations")
    if any(phrase in full_output for phrase in _BANNED_OUTPUT):
        issues.append("remove repetitive stock-video wording")
    if variant:
        dialogue_text = " ".join(
            str(line.get("text") or "") for line in candidate.get("dialogue") or []
        )
        word_count = sum(
            len(str(line.get("text") or "").split())
            for line in candidate.get("dialogue") or []
        )
        if not 56 <= word_count <= 70:
            issues.append(
                f"use 56-70 words to keep experiment durations comparable "
                f"(got {word_count})"
            )
        allowed_numbers = {f"{abs(float(pick.get('change_pct') or 0)):.1f}%"}
        allowed_numbers.update(
            _NUMBER_MENTION.findall(
                " ".join(
                    str(pick.get(field) or "")
                    for field in ("proof", "checkpoint", "invalidation")
                )
            )
        )
        mentions = _NUMBER_MENTION.findall(dialogue_text)
        if len(mentions) > 2 or any(number not in allowed_numbers for number in mentions):
            issues.append("use only the verified move and one supplied proof number")
    if not variant or variant == "baseline_dialogue":
        return issues

    dialogue = candidate.get("dialogue") or []
    first = str(dialogue[0].get("text", "")) if dialogue else ""
    pct = pick.get("change_pct")
    if name_words and not all(word in first.lower() for word in name_words):
        issues.append("put the exact company name in the first spoken line")
    if pct is not None and f"{abs(float(pct)):.1f}%" not in first:
        issues.append("put the exact percentage move in the first spoken line")
    if not _CONTRADICTION.search(first):
        issues.append("put the contradiction in the first spoken line")
    if any(
        len(re.findall(r"[.!?](?:\s|$)", str(line.get("text", "")))) > 1
        for line in dialogue
    ):
        issues.append("use one sentence and one claim per dialogue cut")

    return issues


def _client():
    from openai import OpenAI
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY not set in .env")
    return OpenAI(api_key=key)


def _system_prompt(pick: dict) -> str:
    variant = pick.get("format_variant")
    if not variant:
        return SYSTEM_PROMPT
    prompt = SYSTEM_PROMPT.replace("35-60 word", "56-70 word", 1).replace(
        "Falling Knife or Screaming Buy?",
        "Temporary Shock or Deeper Problem?",
        1,
    ).replace(
        "- Explain why the stock moved, the business mechanism behind it, and what "
        "still needs to be proven.",
        "- Explain only the supplied move, headline, catalyst, and angle. If those "
        "facts do not establish a cause, say the cause is not established.",
        1,
    ).replace(
        "casual, funny, opinionated, and specific",
        "casual, clear, evidence-bound, and specific",
        1,
    ).replace(
        "At most ONE number across the whole conversation. Zero is fine.",
        "At most TWO numbers across the whole conversation: the exact move and one "
        "supplied proof or invalidation number.",
        1,
    )
    duration_rule = (
        "\nCONTROLLED EXPERIMENT: Use 56-70 words total so every format has a "
        "comparable duration. Use only facts supplied in the user message; never "
        "invent a metric, estimate, date, event, claim, deal importance, delay, "
        "revenue effect, motive, forecast, or operational detail."
    )
    return prompt + duration_rule


def _cache_key(pick: dict, model: str) -> str:
    raw = json.dumps(
        {"model": model, "prompt": _system_prompt(pick), "pick": pick},
        sort_keys=True,
        default=str,
    )
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
    if pick.get("proof"):
        lines.append(f"Provided proof: {pick['proof']}")
    if pick.get("checkpoint"):
        lines.append(f"Provided checkpoint: {pick['checkpoint']}")
    if pick.get("invalidation"):
        lines.append(f"Provided invalidation: {pick['invalidation']}")

    if pick.get("reddit_posts"):
        lines.append(f"Reddit buzz: {pick['reddit_posts']} posts")
        discussions = pick.get("reddit_discussions") or []
        if discussions:
            lines.append(f"Reddit talk: {str(discussions[0])[:150]}")

    if pick.get("sector"):
        lines.append(f"Sector: {pick['sector']}")

    if pick.get("format_instructions"):
        lines.append(f"Required format: {pick['format_instructions']}")
    if pick.get("format_variant"):
        lines.append(
            "Required turn plan: exactly four turns with 12-14, 18-22, 8-12, "
            "and 18-22 words respectively; use only the supplied move percentage "
            "and at most one supplied proof or invalidation number."
        )

    return "\n".join(lines)


def _fact_fragment(
    value: object,
    max_words: int,
    *,
    keep_first_number: bool = False,
) -> str:
    seen_number = False

    def replace_number(match: re.Match) -> str:
        nonlocal seen_number
        if keep_first_number and not seen_number:
            seen_number = True
            return match.group(0)
        return ""

    text = _NUMBER_MENTION.sub(replace_number, str(value or ""))
    text = re.sub(r"[.!?]+", "", text)
    text = re.sub(r"\s+", " ", text).strip(" ,:;-")
    text = re.sub(r"\byet$", "", text, flags=re.I).strip(" ,:;-")
    return " ".join(text.split()[:max_words])


def _grounded_experiment_script(pick: dict) -> dict:
    variant = pick["format_variant"]
    if variant not in {
        "move_mechanism",
        "catalyst_checkpoint",
        "radar_invalidation",
    }:
        raise ValueError(f"No grounded template for {variant}")

    raw_name = str(pick.get("name") or pick.get("ticker") or "This company")
    name = re.sub(
        r"\s+(?:inc|corp|corporation|ltd|limited|plc)\.?$",
        "",
        raw_name,
        flags=re.I,
    )
    move = float(pick.get("change_pct") or 0)
    verb = "rose" if move >= 0 else "fell"
    headline = _fact_fragment(
        pick.get("headline") or pick.get("catalyst") or pick.get("thesis"),
        8,
    )
    catalyst = _fact_fragment(pick.get("catalyst") or headline, 6)
    thesis = _fact_fragment(pick.get("thesis") or headline, 8)
    proof = _fact_fragment(
        pick.get("proof") or pick.get("catalyst") or headline,
        10,
        keep_first_number=True,
    )
    checkpoint = _fact_fragment(pick.get("checkpoint") or thesis, 9)
    invalidation = _fact_fragment(
        pick.get("invalidation") or catalyst,
        8,
        keep_first_number=True,
    )
    catalyst_phrase = (
        catalyst
        if catalyst.split()[0].isupper()
        else f"{catalyst[0].lower()}{catalyst[1:]}"
    )
    checkpoint_phrase = (
        checkpoint
        if checkpoint.split()[0].isupper()
        else f"{checkpoint[0].lower()}{checkpoint[1:]}"
    )
    invalidation_phrase = (
        invalidation
        if invalidation.split()[0].isupper()
        else f"{invalidation[0].lower()}{invalidation[1:]}"
    )
    if invalidation_phrase.lower().startswith("break "):
        invalidation_phrase = f"a {invalidation_phrase}"
    first = f"{name} {verb} {abs(move):.1f}%, yet {headline.lower()}."

    if variant == "move_mechanism":
        lines = [
            first,
            f"{proof}, and that is the concrete fact behind this mechanism.",
            "So the headline landed, and the stock still disagreed.",
            f"The next checkpoint is {checkpoint_phrase}, keeping the claim tied to the current evidence.",
        ]
        title = f"{name} {verb.title()} {abs(move):.1f}%: {catalyst}"
    elif variant == "catalyst_checkpoint":
        lines = [
            first,
            f"The stated catalyst is {catalyst_phrase}, backed by one concrete fact: {proof}.",
            "That gives viewers a catalyst, not a conclusion.",
            f"The next checkpoint is {checkpoint_phrase}, which keeps the claim tied to the current evidence.",
        ]
        title = f"{name}: {catalyst} After an {abs(move):.1f}% Move"
    else:
        lines = [
            first,
            f'The market belief being tested is "{thesis}," because that is the angle in the current data.',
            "The price move is the warning, not the verdict.",
            f"The named invalidation is {invalidation_phrase}, which would break that market belief without adding another story.",
        ]
        title = f"{name} {abs(move):.1f}% Move vs {thesis}"

    word_count = sum(len(line.split()) for line in lines)
    if word_count < 56:
        lines[-1] = (
            lines[-1].rstrip(".")
            + ", without assuming facts the current data does not provide."
        )

    dialogue = [
        {"character": "rae2" if index % 2 == 0 else "rae", "text": line}
        for index, line in enumerate(lines)
    ]
    if len(title) > 60:
        title = f"{title[:59].rstrip()}…"
    hashtags = "#stocks #investing #shorts #stocksbrew"
    description = (
        f"{name} moved {abs(move):.1f}%. Catalyst: {catalyst}. "
        f"Current angle: {thesis}."
    )
    description = f"{description[: 199 - len(hashtags)].rstrip()} {hashtags}"
    candidate = {
        "dialogue": dialogue,
        "title": title,
        "description": description,
    }
    issues = dialogue_issues(dialogue)
    issues.extend(experiment_issues(candidate, pick))
    if issues:
        raise ValueError("grounded experiment template failed: " + "; ".join(issues))
    return {**pick, **candidate}


def generate_script(pick: dict, *, model: str = "gpt-4.1-mini") -> dict:
    """Generate a dialogue script + component cards for one story pick.

    Returns: {"dialogue": [{"character": str, "text": str}, ...], "components": [...], ...pick_fields}
    """
    if pick.get("format_variant") not in (None, "baseline_dialogue"):
        return _grounded_experiment_script(pick)

    key = _cache_key(pick, model)
    cached = _read_cache(key)
    if cached:
        cached_result = json.loads(cached)
        candidate = {
            field: cached_result.get(field)
            for field in ("dialogue", "title", "description")
        }
        issues = dialogue_issues(candidate.get("dialogue") or [])
        issues.extend(experiment_issues(candidate, pick))
        if not issues:
            return cached_result

    client = _client()
    user_msg = _format_pick(pick)

    messages = [{"role": "system", "content": _system_prompt(pick)}]
    if not pick.get("format_variant"):
        for shot in FEW_SHOT:
            messages.append({"role": "user", "content": shot["user"]})
            messages.append({"role": "assistant", "content": shot["assistant"]})
    messages.append({"role": "user", "content": user_msg})

    parsed = None
    last_issues: list[str] = []
    for attempt in range(3):
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
        issues.extend(experiment_issues(candidate, pick))
        if not issues:
            parsed = candidate
            break
        last_issues = issues
        messages.extend([
            {"role": "assistant", "content": raw},
            {"role": "user", "content": "Rejected: " + "; ".join(issues) + ". Rewrite the complete JSON."},
        ])

    if parsed is None:
        raise ValueError(
            "generated dialogue failed quality checks: " + "; ".join(last_issues)
        )

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
