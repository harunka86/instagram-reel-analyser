---
name: instagram-reel-summariser
description: Extract and summarise the content of an Instagram reel from its URL. Downloads the reel, transcribes any speech, reads on-screen text from keyframes, and returns a structured summary with a gist, key points, and full transcript. Use whenever the user shares an Instagram reel link and wants to know what is in it, asks to "summarise this reel", "what does this reel say", "extract the content of this Instagram video", or pastes an instagram.com/reel/ URL with any request to understand or process it.
---

# Instagram Reel Summariser

Single-URL, on-demand pipeline. Not a bulk scraper — do not loop this over profiles, hashtags, or follower lists.

## Usage

```bash
python scripts/pipeline.py <url> \
  [--cookies FILE] \
  [--whisper-model base|small|medium|large-v3] \
  [--cache-dir ~/.cache/reel-summariser] \
  [--no-cache] \
  [--json]
```

`ffmpeg` must be on PATH. Install deps first: `pip install -r requirements.txt`.

## What it does

1. Fetches the reel via yt-dlp (video + metadata: caption, author, duration).
2. Extracts 16kHz mono audio (skips cleanly if the reel has no audio track).
3. Extracts up to 8 keyframes on scene cuts (falls back to 4 fixed-interval frames for static/talking-head reels).
4. Transcribes audio locally with faster-whisper (`vad_filter=True` to avoid hallucinating lyrics on music-only reels).
5. Sends frames + caption + transcript to Claude for a structured summary (gist, key points, on-screen text, content type).
6. Writes `summary.json` to the cache dir and prints a markdown summary.

## Known failure modes

- yt-dlp breaks when Instagram changes internals. Errors surface loudly with a suggestion to `pip install -U yt-dlp` — this tool does not retry silently.
- Login-walled reels need `--cookies path/to/cookies.txt`. No credentials are ever hardcoded.
- Music-only reels produce `has_speech: false` and an empty transcript — this is expected, not a bug.
- Reruns on the same URL hit the cache (keyed on shortcode) and skip re-downloading/re-transcribing. Use `--no-cache` to force a rebuild.

## Not built (see spec section 8)

Notion write, batch mode over a URL list, and a `large-v3`-by-default toggle are stretch goals, not implemented here.
