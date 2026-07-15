#!/usr/bin/env python3
"""Instagram reel summariser: fetch, extract, transcribe, summarise a single reel URL."""

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def check_ffmpeg():
    if shutil.which("ffmpeg") is None:
        sys.exit(
            "ERROR: ffmpeg not found on PATH. Install it and re-run "
            "(e.g. `choco install ffmpeg` on Windows, `brew install ffmpeg` on macOS, "
            "`apt install ffmpeg` on Debian/Ubuntu)."
        )


def parse_shortcode(url: str) -> str:
    """Accept /reel/, /reels/, and /p/ URL forms; strip query params first."""
    path = urlparse(url).path
    match = re.search(r"/(?:reel|reels|p)/([^/]+)/?", path)
    if not match:
        sys.exit(
            f"ERROR: could not parse a shortcode out of '{url}'. "
            "Expected a URL like https://www.instagram.com/reel/Cxxxxxxxxxx/"
        )
    return match.group(1)


# --- [1] Fetch --------------------------------------------------------------

def fetch_reel(url: str, shortcode: str, cache_dir: Path, cookies_path: str | None) -> dict:
    reel_dir = cache_dir / shortcode
    reel_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = reel_dir / "metadata.json"
    video_path = reel_dir / "video.mp4"

    if video_path.exists() and metadata_path.exists():
        return json.loads(metadata_path.read_text(encoding="utf-8"))

    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        sys.exit(
            "ERROR: yt-dlp is not installed. Run `pip install -U yt-dlp` and retry."
        )

    ydl_opts = {
        "outtmpl": str(reel_dir / "video.%(ext)s"),
        "format": "best[ext=mp4]/best",
        "quiet": True,
    }
    if cookies_path:
        ydl_opts["cookiefile"] = cookies_path

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as exc:
        sys.exit(
            f"ERROR: yt-dlp failed to fetch '{url}':\n{exc}\n\n"
            "Instagram changes its internals often, breaking yt-dlp. Try:\n"
            "  pip install -U yt-dlp\n"
            "If that doesn't fix it, this reel may be login-walled (pass --cookies) "
            "or the URL/shortcode may be wrong. Not retrying automatically."
        )

    # yt-dlp may pick a different extension than .mp4; normalise the on-disk name.
    downloaded_ext = info.get("ext", "mp4")
    downloaded_path = reel_dir / f"video.{downloaded_ext}"
    if downloaded_path != video_path and downloaded_path.exists():
        downloaded_path.rename(video_path)

    metadata = {
        "id": info.get("id", shortcode),
        "uploader": info.get("uploader"),
        "description": info.get("description", ""),
        "duration": info.get("duration"),
        "webpage_url": info.get("webpage_url", url),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


# --- [2] Audio extraction ----------------------------------------------------

def extract_audio(video_path: Path, reel_dir: Path) -> tuple[Path | None, bool]:
    probe = subprocess.run(
        ["ffmpeg", "-i", str(video_path)],
        capture_output=True,
        text=True,
    )
    has_audio = "Audio:" in probe.stderr
    if not has_audio:
        return None, False

    audio_path = reel_dir / "audio.wav"
    if audio_path.exists():
        return audio_path, True

    subprocess.run(
        [
            "ffmpeg", "-i", str(video_path),
            "-vn", "-ac", "1", "-ar", "16000", "-f", "wav",
            str(audio_path), "-y",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return audio_path, True


# --- [3] Keyframe extraction --------------------------------------------------

def extract_frames(video_path: Path, reel_dir: Path, duration: float | None) -> list[Path]:
    frames_dir = reel_dir / "frames"
    existing = sorted(frames_dir.glob("frame_*.jpg")) if frames_dir.exists() else []
    if existing:
        return existing[:8]

    frames_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-i", str(video_path),
            "-vf", "select='gt(scene,0.3)',scale=640:-1",
            "-vsync", "vfr",
            str(frames_dir / "frame_%03d.jpg"),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    frames = sorted(frames_dir.glob("frame_*.jpg"))

    if len(frames) < 3:
        # Fixed-interval fallback: 4 frames evenly spaced across the duration.
        for f in frames:
            f.unlink()
        dur = duration or 10.0
        n = 4
        subprocess.run(
            [
                "ffmpeg", "-i", str(video_path),
                "-vf", f"fps={n}/{dur},scale=640:-1",
                "-frames:v", str(n),
                str(frames_dir / "frame_%03d.jpg"),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        frames = sorted(frames_dir.glob("frame_*.jpg"))
    elif len(frames) > 8:
        # Sample 8 evenly across the detected scene cuts.
        step = len(frames) / 8
        frames = [frames[int(i * step)] for i in range(8)]

    return frames


# --- [4] Transcription --------------------------------------------------------

def transcribe(audio_path: Path | None, reel_dir: Path, whisper_model: str) -> tuple[str, bool, str | None]:
    transcript_path = reel_dir / "transcript.txt"
    language_path = reel_dir / "language.txt"
    if transcript_path.exists():
        text = transcript_path.read_text(encoding="utf-8")
        language = language_path.read_text(encoding="utf-8").strip() or None if language_path.exists() else None
        return text, len(text.strip()) >= 15, language

    if audio_path is None:
        transcript_path.write_text("", encoding="utf-8")
        language_path.write_text("", encoding="utf-8")
        return "", False, None

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit(
            "ERROR: faster-whisper is not installed. Run `pip install -U faster-whisper` and retry."
        )

    model = WhisperModel(whisper_model, device="cpu", compute_type="int8")
    segments, info = model.transcribe(str(audio_path), vad_filter=True)
    text = " ".join(seg.text.strip() for seg in segments).strip()

    transcript_path.write_text(text, encoding="utf-8")
    language_path.write_text(info.language or "", encoding="utf-8")
    has_speech = len(text) >= 15
    return text, has_speech, info.language


# --- [5] Summarisation ---------------------------------------------------------

SYSTEM_PROMPT = """You are summarising an Instagram reel. You have been given keyframes from the video, the creator's caption, and a transcript of the audio (which may be empty if the reel has no speech).

Read on-screen text from the frames carefully. Many reels carry their entire message through text overlays rather than speech.

Respond with JSON only, no preamble and no markdown fences:
{
  "gist": "one sentence",
  "key_points": ["...", "..."],
  "on_screen_text": "all text visible in the frames, in order",
  "content_type": "talking_head | tutorial | text_overlay | product_demo | other",
  "has_speech": true|false
}"""


def build_message_content(frames: list[Path], metadata: dict, transcript: str, has_speech: bool) -> list[dict]:
    import base64

    content = []
    for frame in frames:
        b64 = base64.standard_b64encode(frame.read_bytes()).decode("utf-8")
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
        })

    transcript_note = transcript if has_speech else "(no speech detected in this reel)"
    text_block = (
        f"Author: @{metadata.get('uploader')}\n"
        f"Duration: {metadata.get('duration')}s\n"
        f"Caption: {metadata.get('description', '')}\n"
        f"Transcript: {transcript_note}"
    )
    content.append({"type": "text", "text": text_block})
    return content


def strip_json_fences(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


def summarise(frames: list[Path], metadata: dict, transcript: str, has_speech: bool) -> dict:
    try:
        import anthropic
    except ImportError:
        sys.exit(
            "ERROR: anthropic package is not installed. Run `pip install -U anthropic` and retry."
        )

    client = anthropic.Anthropic()
    content = build_message_content(frames, metadata, transcript, has_speech)

    def call(nudge: str | None = None) -> str:
        messages = [{"role": "user", "content": content}]
        if nudge:
            messages.append({"role": "assistant", "content": "{"})
            messages.append({"role": "user", "content": nudge})
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        return resp.content[0].text

    raw = call()
    try:
        return json.loads(strip_json_fences(raw))
    except json.JSONDecodeError:
        pass

    raw_retry = call(nudge="Return valid JSON only, matching the schema exactly, no other text.")
    try:
        return json.loads(strip_json_fences(raw_retry))
    except json.JSONDecodeError as exc:
        sys.exit(
            f"ERROR: Claude did not return valid JSON after a retry.\n"
            f"Parse error: {exc}\n\nRaw response:\n{raw_retry}"
        )


# --- [6] Output ----------------------------------------------------------------

def render_markdown(summary: dict, metadata: dict, transcript: str) -> str:
    key_points = "\n".join(f"- {p}" for p in summary.get("key_points", []))
    return f"""## @{metadata.get('uploader')} - {summary.get('content_type')}

**Gist:** {summary.get('gist')}

**Key points:**
{key_points}

**On-screen text:** {summary.get('on_screen_text')}

**Caption:** {metadata.get('description', '')}

<details><summary>Full transcript</summary>

{transcript or '(no speech)'}

</details>
"""


def main():
    parser = argparse.ArgumentParser(description="Summarise an Instagram reel from its URL.")
    parser.add_argument("url", help="Instagram reel URL")
    parser.add_argument("--cookies", default=None, help="Path to a cookies.txt file for login-walled reels")
    parser.add_argument("--whisper-model", default="base", choices=["base", "small", "medium", "large-v3"])
    parser.add_argument("--cache-dir", default=str(Path.home() / ".cache" / "reel-summariser"))
    parser.add_argument("--no-cache", action="store_true", help="Ignore any cached artifacts and rebuild")
    parser.add_argument("--json", action="store_true", help="Print raw JSON instead of markdown")
    args = parser.parse_args()

    check_ffmpeg()

    cache_dir = Path(args.cache_dir)
    shortcode = parse_shortcode(args.url)
    reel_dir = cache_dir / shortcode

    if args.no_cache and reel_dir.exists():
        shutil.rmtree(reel_dir)

    summary_path = reel_dir / "summary.json"
    if not args.no_cache and summary_path.exists():
        output = json.loads(summary_path.read_text(encoding="utf-8"))
        if args.json:
            print(json.dumps(output, indent=2))
        else:
            print(render_markdown(output, output, output.get("transcript", "")))
        return

    metadata = fetch_reel(args.url, shortcode, cache_dir, args.cookies)
    video_path = reel_dir / "video.mp4"

    audio_path, has_audio = extract_audio(video_path, reel_dir)
    frames = extract_frames(video_path, reel_dir, metadata.get("duration"))

    if has_audio:
        transcript, has_speech, detected_language = transcribe(audio_path, reel_dir, args.whisper_model)
    else:
        transcript, has_speech, detected_language = "", False, None

    summary = summarise(frames, metadata, transcript, has_speech)

    output = {
        **metadata,
        **summary,
        "has_audio": has_audio,
        "detected_language": detected_language,
        "transcript": transcript,
    }
    (reel_dir / "summary.json").write_text(json.dumps(output, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(output, indent=2))
    else:
        print(render_markdown(summary, metadata, transcript))


if __name__ == "__main__":
    main()
