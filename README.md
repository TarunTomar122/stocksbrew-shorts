# stocksbrew-shorts

Automated short-form video pipeline that generates brainrot-style finance shorts with two-character dialogue, visual component cards, and auto-scheduling to YouTube + Instagram.

**Live at:** [stocksbrew.online](https://stocksbrew.online) | **YouTube:** [@stocksbrew.online](https://www.youtube.com/@stocksbrew.online)

## What it does

1. **Pulls trending tickers** from Firebase (daily anomalies, heat list, reddit buzz)
2. **Generates dialogue scripts** via OpenAI (two characters talking about the stock)
3. **Creates avatar videos** via Runway's `gwm1_avatars` model (one per character line)
4. **Composites brainrot shorts** with gameplay backgrounds, speaker images, subtitles, and visual component cards
5. **Uploads to Cloudinary** and **schedules to Buffer** (YouTube + Instagram)

## Features

- **Two-character dialogue** — rae2 (blunt, casual) and rae (clever, sarcastic) discuss stock stories
- **5 visual component cards** — big move, company card, context quote, verdict stamp, reddit buzz
- **One-word subtitles** with Whisper word-level timing
- **Auto mode** — pulls data, generates scripts, renders videos, and schedules posts on cron
- **4x daily scheduling** via GitHub Actions (3pm, 7pm, 9pm, 1am IST)

## Tech stack

- **Python 3.11** — core pipeline
- **Runway ML** — avatar video generation (`gwm1_avatars`)
- **OpenAI** — script generation (`gpt-4o-mini`)
- **Firebase Admin** — Firestore data (anomalies, heat list, reddit)
- **faster-whisper** — word-level transcription for subtitles
- **Pillow** — visual component card rendering
- **ffmpeg** — video compositing and processing
- **Cloudinary** — video hosting
- **Buffer API** — social media scheduling
- **GitHub Actions** — cron scheduling

## Layout

```
.
├── lib/                       # Modular Python helpers
│   ├── avatar.py              # Runway avatar video generation (single + dialogue)
│   ├── brainrot.py            # The compositing pipeline
│   ├── buffer.py              # Buffer API client (YouTube + Instagram scheduling)
│   ├── catalog.py             # JSON catalog lookup
│   ├── clipper.py             # Cut N random clips from a source
│   ├── components.py          # Visual component card renderers
│   ├── ffmpeg.py              # Low-level ffmpeg/ffprobe wrappers
│   ├── firebase.py            # Firestore admin client (anomalies, heat list, reddit)
│   ├── hosting.py             # Cloudinary video hosting
│   ├── storygen.py            # OpenAI-powered dialogue script generation
│   ├── subtitles.py           # Whisper-driven drawtext filter builder
│   └── transcribe.py          # faster-whisper word timestamps
├── scripts/
│   └── build.py               # One-off CLI: avatar | brainrot | clip
├── assets/
│   ├── gameplay/              # Background gameplay clips
│   └── speaker/               # Speaker images (charimage.png, char2image.png)
├── catalog/
│   └── gameplay.json          # Index of gameplay clips
├── scripts/queue/             # Drop script JSONs here (or let --auto)
├── runner.py                  # Cron entrypoint
├── package.json               # npm script aliases
└── requirements.txt
```

## Quick start

```bash
# Clone and setup
git clone https://github.com/TarunTomar122/stocksbrew-shorts.git
cd stocksbrew-shorts
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure secrets
cp .env.example .env
# Edit .env with your API keys

# Drop Firebase service account JSON
# (download from Firebase Console → Project Settings → Service Accounts)

# Verify connections
npm run fb-test
npm run buffer-test
npm run cloudinary-test

# Run the pipeline
npm run auto
```

## Auto mode (the daily driver)

One command pulls today's hottest tickers from Firebase, writes dialogue scripts via OpenAI, renders avatar videos, composites brainrot shorts, and schedules to YouTube + Instagram:

```bash
npm run auto                  # 1 short from today's top ticker
npm run auto-batch            # 5 shorts in one go
```

Flags for finer control:

```bash
npm run run -- --auto --auto-count 3 --auto-market US --auto-min-score 30
npm run run -- --auto --auto-skip-existing   # don't redo tickers already queued today
```

What `--auto` does:
1. Reads daily anomalies + heat list from Firestore
2. Pulls reddit buzz data for context
3. Calls OpenAI to write a 2-4 line dialogue between rae2 and rae
4. Generates one Runway avatar video per dialogue line, concatenates them
5. Runs Whisper for word-level subtitle timing
6. Composites gameplay background + speaker images + subtitles + component cards
7. Uploads to Cloudinary and schedules to Buffer

## Manual / queue usage

Drop a script JSON into `scripts/queue/`:

```json
{
  "id": "nvda-2026-06-18",
  "dialogue": [
    {"character": "rae2", "text": "Hey you see what Nvidia did today?"},
    {"character": "rae", "text": "Everyone's obsessed but nobody's watching Broadcom."}
  ],
  "components": [
    {"type": "big_move", "show_at": 0.1, "data": {"pct": -6.7, "direction": "down", "name": "Nvidia"}}
  ]
}
```

Then process the queue:

```bash
npm run run                  # process one script and exit
npm run run -- --max 10      # process up to 10
npm run loop                 # long-running, polls every 30s
npm run queue                # dry-run, show what's queued
```

## One-off usage

```bash
# Generate a single avatar video
npm run avatar -- --text "Nvidia just ripped higher" --avatar rae2

# Compose brainrot from an existing avatar video
npm run brainrot -- \
  --avatar-video output/avatar-rae2-XXXXXXXX.mp4 \
  --gameplay assets/gameplay/randombg_01_26s.mp4 \
  --subtitles

# Re-sample your gameplay library from a new source video
npm run clip -- --source my-new-brainrot.mp4 --count 20 --seed 42
```

## Cron (GitHub Actions)

The pipeline runs 4x daily via GitHub Actions:
- **3:00 PM IST** (9:30 UTC)
- **7:00 PM IST** (13:30 UTC)
- **9:00 PM IST** (15:30 UTC)
- **1:00 AM IST** (19:30 UTC)

Also triggerable manually from the Actions tab.

### Setup (one-time)

1. Go to repo **Settings → Secrets and variables → Actions**
2. Add these **Repository secrets**:

| Secret | Description |
|--------|-------------|
| `RUNWAYML_API_SECRET` | Runway API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `BUFFER_API_KEY` | Buffer API key |
| `CLOUDINARY_CLOUD_NAME` | Cloudinary cloud name |
| `CLOUDINARY_API_KEY` | Cloudinary API key |
| `CLOUDINARY_API_SECRET` | Cloudinary API secret |
| `FIREBASE_CREDENTIALS_JSON` | Entire contents of your Firebase service account JSON |

3. Done. The workflow runs automatically at the scheduled times.

### Manual run

GitHub Actions tab → "Daily Shorts Pipeline" → "Run workflow".

## Diagnostics

```bash
npm run fb-test               # verify Firebase connection + data freshness
npm run buffer-test           # verify Buffer API + channel discovery
npm run cloudinary-test       # verify Cloudinary upload works
npm run list-avatars          # list all Runway avatars in your account
```

## Caching

- **Whisper transcripts** → `.cache/transcripts/<videoname>.jsonl` (reused if source video unchanged)
- **OpenAI scripts** → `.cache/stories/<hash>.json` (keyed on pick data, avoids re-billing)

## Avatar name resolution

`--avatar` accepts either a known short name (`rae2`, `rae`) or a raw UUID. To list all avatars:

```bash
npm run list-avatars
```

## License

MIT

Built by [Tarun Tomar](https://twitter.com/tarat_211) for [StocksBrew](https://stocksbrew.online)
