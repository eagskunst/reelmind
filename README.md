# reelmind

Local-first library of your saved TikTok / Instagram / YouTube videos that you can *ask questions about*.

- Feed it video URLs, whole collections, or your official data exports.
- It downloads each video, transcribes the audio locally, looks at a few frames,
  and stores a plain-language summary plus structured places/events in a local SQLite DB.
- Then ask things like *"what restaurant can I go to eat?"* or *"what events are happening near me soon?"* — from the CLI or a small local web UI.

Everything runs on your PC. The only external call is a cheap, OpenAI-compatible chat API
(Gemini free tier, OpenRouter, OpenAI, or fully-local Ollama).

License: GPL-3.0-or-later (see LICENSE).

## Install

Requirements: Python ≥ 3.11, [uv](https://docs.astral.sh/uv/), `ffmpeg`/`ffprobe` on PATH.

```bash
sudo apt install ffmpeg          # if missing
uv sync                          # creates .venv and installs deps
uv run reelmind --help
```

## Quick start

```bash
export GEMINI_API_KEY=...        # free key: https://aistudio.google.com/apikey
uv run reelmind add "https://www.tiktok.com/@someone/video/7123..."
uv run reelmind ask "what restaurant can I go to eat?"
uv run reelmind serve            # http://127.0.0.1:8765
```

## Configuration

`reelmind init` writes a commented `reelmind.toml` in the current directory.
Search order: `./reelmind.toml`, then `~/.config/reelmind/config.toml`.
Everything can also be overridden with `REELMIND_*` env vars
(e.g. `REELMIND_LLM_MODEL`, `REELMIND_USER_HOME_LOCATION`).
See `reelmind.example.toml` for a full annotated example.

### LLM providers (any OpenAI-compatible endpoint)

**Gemini (default, free tier)** — get a key at <https://aistudio.google.com/apikey>:

```toml
[llm]
base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
model = "gemini-2.5-flash-lite"
api_key_env = "GEMINI_API_KEY"
```

**OpenRouter:**

```toml
[llm]
base_url = "https://openrouter.ai/api/v1"
model = "google/gemini-2.5-flash-lite"
api_key_env = "OPENROUTER_API_KEY"
```

**Ollama (fully free & local):**

```toml
[llm]
base_url = "http://localhost:11434/v1"
model = "qwen3:8b"    # any pulled model with JSON + vision support
# api_key_env can point at anything; Ollama ignores the key
```

**OpenAI:**

```toml
[llm]
base_url = "https://api.openai.com/v1"
model = "gpt-4.1-mini"
api_key_env = "OPENAI_API_KEY"
```

`api_key_env` names *any* environment variable to read the key from;
`REELMIND_LLM_API_KEY` is also always accepted.

### Transcription

Default `faster-whisper` runs locally and is free. Tune in `[transcription]`:
`backend = "faster-whisper" | "openai" | "none"`, `model = "small"` (whisper size,
or API model name for the `openai` backend), `device`, `compute_type`.

### Cookies (Instagram)

Instagram usually requires login cookies. Point yt-dlp at your browser:

```toml
[platforms.instagram]
cookies_from_browser = "chrome"     # or firefox, edge, ...
# cookies_file = "/path/to/cookies.txt"
```

Same works under `[platforms.tiktok]` if needed.

### Location

```toml
[user]
home_location = "Madrid, Spain"   # "near me" resolves to this city
summary_language = "en"
```

## Getting your saved videos out of the apps

**TikTok:** Profile → Settings → *Download your data* → JSON. Unzip (or feed the `.zip`
directly) and run `uv run reelmind import TikTok_Data.zip`. Favorite/saved video links are
extracted automatically — the importer walks every JSON value at any depth, so export schema
changes don't break it.

**Instagram:** Accounts Center → *Your information and permissions* → *Download your
information* → JSON → includes `saved_posts.json`. `uv run reelmind import` on the zip or folder.

Any `.json/.txt/.csv/.html` file, directory tree, or `.zip` works: all text content is scanned
for URLs and only supported-platform links are kept, normalized and deduplicated.

Also: `reelmind add` accepts list/collection URLs (e.g. a TikTok collection) and expands them.

## Usage

```bash
reelmind init                          # write default config
reelmind add URL... [--file urls.txt] [--no-process]
reelmind import EXPORT.zip [--limit 20] [--no-process]
reelmind process [--retry-failed] [--limit 10]
reelmind list [--category restaurant] [--city madrid] [--upcoming] [--search sushi]
reelmind show 3
reelmind ask "what events are happening near me soon?"
reelmind serve [--port 8765]           # local web UI
reelmind platforms                     # registered platforms
reelmind stats                         # counts + token usage
```

Data lives in `data_dir` (default `~/.local/share/reelmind`): `reelmind.db` + `cache/`.
Downloaded media is deleted after processing unless `keep_media = true`.

## Cost notes

Cheap by design:

- Transcription: local faster-whisper → **free**.
- Analysis: 4 small JPEG frames + caption + truncated transcript ≈ **1–3k tokens/video**;
  on `gemini-2.5-flash-lite` that's fractions of a cent — the Gemini free tier covers it.
- Questions: one tiny planning call + one answer call with compact candidate records.
- Token usage per model is logged (`reelmind stats`).

## Adding a platform

One file in `src/reelmind/platforms/` + registration. Subclass `YtDlpPlatform` and
implement `matches()` / `parse()` (return `None` for list URLs); override `expand()` or
`download()` only if needed:

```python
from reelmind.models import VideoRef
from reelmind.platforms.base import register_platform
from reelmind.platforms.ytdlp import YtDlpPlatform


class VimeoPlatform(YtDlpPlatform):
    name = "vimeo"

    def matches(self, url):
        return "vimeo.com" in url

    def parse(self, url):
        vid = url.rstrip("/").rsplit("/", 1)[-1]
        return VideoRef(platform=self.name, video_id=vid, url=url) if vid.isdigit() else None


register_platform(VimeoPlatform())
```

Import the module in `platforms/__init__.py` and it's picked up everywhere
(CLI, importer, web UI) automatically.

## Development

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run pytest -q        # no network; LLM/downloader/transcriber are faked
```
