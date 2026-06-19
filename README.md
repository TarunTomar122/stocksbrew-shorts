# aivideos-stocksbrew

Brainrot short-form video pipeline for stocksbrew.online.

- **Avatar voice** from Runway's `gwm1_avatars` model (your custom avatar)
- **Background** from a looped gameplay clip library
- **Speaker image** composited in a corner (no crop, no circle)
- **One-word subtitles** with Whisper word-level timing
- **Auto mode** — pulls trending tickers from stocksbrew Firebase, generates
  scripts via OpenAI, and produces finished shorts on cron

## Layout

```
.
├── lib/                       # Modular Python helpers
│   ├── avatar.py              # Runway avatar video generation
│   ├── brainrot.py            # The compositing pipeline
│   ├── catalog.py             # JSON catalog lookup
│   ├── clipper.py             # Cut N random clips from a source
│   ├── ffmpeg.py              # Low-level ffmpeg/ffprobe wrappers
│   ├── firebase.py            # Firestore admin client (heat list, prices)
│   ├── storygen.py            # OpenAI-powered script generation
│   ├── subtitles.py           # Whisper-driven drawtext filter builder
│   └── transcribe.py          # faster-whisper word timestamps
├── scripts/
│   └── build.py               # One-off CLI: avatar | brainrot | clip
├── assets/
│   ├── gameplay/              # randombg_*.mp4 background clips
│   └── speaker/charimage.png  # Default speaker overlay
├── catalog/
│   └── gameplay.json          # Index of gameplay clips
├── scripts/queue/             # ← drop script JSONs here (or let --auto)
│   ├── done/                  #   processed successfully
│   └── failed/                #   errors for inspection
├── .cache/                    # Whisper transcripts + OpenAI story cache
├── output/                    # Generated avatar and brainrot mp4s
├── firebase-credentials.json  # Service account (gitignored)
├── runner.py                  # Cron entrypoint
├── package.json               # npm script aliases
└── requirements.txt
```

## Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Required secrets (all gitignored)
echo "RUNWAYML_API_SECRET=key_..." > .env
echo "OPENAI_API_KEY=sk-..." >> .env
echo "FIREBASE_CREDENTIALS_PATH=firebase-credentials.json" >> .env
# Drop the Firebase service account JSON as firebase-credentials.json
```

## Auto mode (the daily driver)

One command pulls today's hottest tickers from stocksbrew Firebase, writes
viral-style scripts via OpenAI, queues them, and renders the videos:

```bash
npm run auto                  # 1 short from today's top heat-list ticker
npm run auto-batch            # 5 shorts in one go
```

Flags for finer control:

```bash
npm run run -- --auto --auto-count 3 --auto-market US --auto-min-score 30
npm run run -- --auto --auto-skip-existing   # don't redo tickers already queued today
```

What `--auto` does:
1. Reads `tm_heat_list_view/US` from Firestore (top stocks worth attention today)
2. Denormalizes each pick with `tm_latest_prices/{instrument_id}` for the % change
3. Calls OpenAI `gpt-4o-mini` to write a 30–45 word brainrot-style script per pick
4. Drops a script JSON into `scripts/queue/`
5. Processes the queue: Runway avatar → Whisper subtitles → brainrot composite

## Manual / queue usage

Drop a script JSON into `scripts/queue/`:

```json
{
  "id": "nvda-2026-06-18",
  "text": "NVDA just ripped 4 percent higher and nobody saw it coming.",
  "avatar": "rae2"
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
npm run avatar -- --text "NVDA just ripped 4 percent higher" --avatar rae2

# Compose brainrot from an existing avatar video (random bg, with subtitles)
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

1. Push this repo to GitHub
2. Go to repo **Settings → Secrets and variables → Actions**
3. Add these **secrets**:
   - `RUNWAYML_API_SECRET` — from your Runway dashboard
   - `OPENAI_API_KEY` — from OpenAI dashboard
   - `BUFFER_API_KEY` — from Buffer API settings
   - `CLOUDINARY_CLOUD_NAME` — e.g. `di3dj38ic`
   - `CLOUDINARY_API_KEY` — from Cloudinary dashboard
   - `CLOUDINARY_API_SECRET` — from Cloudinary dashboard
   - `FIREBASE_CREDENTIALS_JSON` — paste the **entire contents** of your `firebase-credentials.json` file

4. Done. The workflow runs automatically at the scheduled times.

### Manual run

GitHub Actions tab → "Daily Shorts Pipeline" → "Run workflow".

## Diagnostics

```bash
npm run fb-test               # verify Firebase connection + heat-list freshness
npm run list-avatars          # list all Runway avatars in your account
```

## Caching

- **Whisper transcripts** → `.cache/transcripts/<videoname>.jsonl` (reused if
  the source video hasn't changed)
- **OpenAI scripts** → `.cache/stories/<hash>.json` (keyed on the heat-list
  pick data, so the same ticker+signals won't re-bill OpenAI)

## Avatar name resolution

`--avatar` accepts either a known short name (`rae2`, `rae`) or a raw UUID.
To list all avatars in your Runway account:

```bash
npm run list-avatars
```
