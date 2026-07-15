# instagram-reel-summariser

Takes an Instagram reel URL, extracts speech + on-screen text + caption, returns a structured summary.

Distributed as a single-skill Claude Code plugin — `SKILL.md` sits at the plugin root (no `skills/` subdirectory needed), per the single-skill plugin convention.

## Setup

```bash
pip install -r requirements.txt
```

`ffmpeg` must be on PATH. `ANTHROPIC_API_KEY` must be set in the environment for the summarisation step (e.g. via a `.env` file at the plugin root, loaded automatically — see `scripts/pipeline.py`).

## Install and test as a plugin

Load it locally without installing, for development/testing:

```bash
claude --plugin-dir /path/to/instagram-reel-summariser
```

Then just ask Claude to summarise a reel, or paste a reel URL — the skill triggers automatically. No slash command needed since this is a model-invoked skill, not a command.

To install permanently via the plugin manager: `/plugin marketplace add <your-marketplace>` then `/plugin install instagram-reel-summariser`.

## Run the pipeline directly (no Claude Code needed)

```bash
python scripts/pipeline.py "https://www.instagram.com/reel/Cxxxxxxxxxx/"
```

See `SKILL.md` for full flag reference and known failure modes.
