"""Config: ./reelmind.toml, else ~/.config/reelmind/config.toml, plus REELMIND_* env overrides."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

DEFAULT_CATEGORIES = [
    "restaurant",
    "cafe_bar",
    "event",
    "travel_place",
    "activity",
    "recipe",
    "shopping",
    "other",
]

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEFAULT_MODEL = "gemini-2.5-flash-lite"


class LLMConfig(BaseModel):
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    answer_model: str | None = None  # defaults to `model` when unset
    api_key_env: str = "GEMINI_API_KEY"

    @property
    def answer_model_name(self) -> str:
        return self.answer_model or self.model

    def api_key(self) -> str:
        """Key from REELMIND_LLM_API_KEY, else the env var named by api_key_env, else a dummy.

        Local servers like Ollama accept any non-empty key.
        """
        return os.environ.get("REELMIND_LLM_API_KEY") or os.environ.get(self.api_key_env) or "none"


class TranscriptionConfig(BaseModel):
    backend: Literal["faster-whisper", "openai", "none"] = "faster-whisper"
    model: str = "small"
    device: str = "auto"
    compute_type: str = "int8"


class FramesConfig(BaseModel):
    count: int = 4
    max_width: int = 512


class UserConfig(BaseModel):
    home_location: str | None = None  # e.g. "Madrid, Spain"
    summary_language: str = "en"


class PlatformConfig(BaseModel):
    cookies_from_browser: str | None = None  # e.g. "chrome"
    cookies_file: str | None = None


class Config(BaseModel):
    data_dir: Path = Field(default_factory=lambda: Path.home() / ".local" / "share" / "reelmind")
    keep_media: bool = False
    categories: list[str] = Field(default_factory=lambda: list(DEFAULT_CATEGORIES))
    llm: LLMConfig = Field(default_factory=LLMConfig)
    transcription: TranscriptionConfig = Field(default_factory=TranscriptionConfig)
    frames: FramesConfig = Field(default_factory=FramesConfig)
    user: UserConfig = Field(default_factory=UserConfig)
    platforms: dict[str, PlatformConfig] = Field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "reelmind.db"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    def platform_config(self, name: str) -> PlatformConfig:
        return self.platforms.get(name, PlatformConfig())


_ENV_OVERRIDES: dict[str, tuple[str, ...]] = {
    "REELMIND_DATA_DIR": ("data_dir",),
    "REELMIND_KEEP_MEDIA": ("keep_media",),
    "REELMIND_LLM_BASE_URL": ("llm", "base_url"),
    "REELMIND_LLM_MODEL": ("llm", "model"),
    "REELMIND_LLM_ANSWER_MODEL": ("llm", "answer_model"),
    "REELMIND_LLM_API_KEY_ENV": ("llm", "api_key_env"),
    "REELMIND_TRANSCRIPTION_BACKEND": ("transcription", "backend"),
    "REELMIND_TRANSCRIPTION_MODEL": ("transcription", "model"),
    "REELMIND_USER_HOME_LOCATION": ("user", "home_location"),
    "REELMIND_SUMMARY_LANGUAGE": ("user", "summary_language"),
}


def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    data = {k: (dict(v) if isinstance(v, dict) else v) for k, v in data.items()}
    for env, path in _ENV_OVERRIDES.items():
        if env not in os.environ:
            continue
        value: object = os.environ[env]
        if path == ("keep_media",):
            value = str(value).lower() in ("1", "true", "yes", "on")
        target = data
        for key in path[:-1]:
            target = target.setdefault(key, {})
        target[path[-1]] = value
    return data


def default_config_path() -> Path | None:
    local = Path.cwd() / "reelmind.toml"
    if local.exists():
        return local
    home = Path.home() / ".config" / "reelmind" / "config.toml"
    if home.exists():
        return home
    return None


def load_config(path: Path | None = None) -> Config:
    cfg_path = path or default_config_path()
    data: dict[str, Any] = {}
    if cfg_path is not None and cfg_path.exists():
        data = tomllib.loads(cfg_path.read_text())
    return Config.model_validate(_apply_env_overrides(data))


DEFAULT_CONFIG_TOML = """\
# reelmind configuration
# Search order: ./reelmind.toml then ~/.config/reelmind/config.toml
# Any value below can also be set via REELMIND_* environment variables.

# Where the database and media cache live.
# data_dir = "~/.local/share/reelmind"

# Keep downloaded videos after processing (default false = delete to save space).
# keep_media = false

[llm]
# Any OpenAI-compatible endpoint works.
# Gemini (free tier): https://aistudio.google.com/apikey -> export GEMINI_API_KEY=...
# base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
# model = "gemini-2.5-flash-lite"
# answer_model = "gemini-2.5-flash-lite"   # model used for answering questions
# api_key_env = "GEMINI_API_KEY"           # env var to read the key from
#
# Ollama (fully free & local):
# base_url = "http://localhost:11434/v1"
# model = "qwen3:8b"   # any model with JSON + vision support you have pulled
#
# OpenAI / OpenRouter: base_url = "https://api.openai.com/v1" (or openrouter.ai/api/v1),
# api_key_env = "OPENAI_API_KEY" / "OPENROUTER_API_KEY"

[transcription]
# backend = "faster-whisper"   # "faster-whisper" (local, free) | "openai" (API) | "none"
# model = "small"              # whisper size for faster-whisper, or API model name
# device = "auto"              # auto | cpu | cuda
# compute_type = "int8"

[frames]
# count = 4          # frames extracted per video (on-screen text often has names/addresses)
# max_width = 512    # pixels; keeps token cost low

[user]
# home_location = "Madrid, Spain"   # used when you ask "near me"
# summary_language = "en"           # language of stored summaries/answers

# Categories the LLM assigns. Edit freely; unknown categories fall back to "other".
# categories = ["restaurant", "cafe_bar", "event", "travel_place", "activity",
#               "recipe", "shopping", "other"]

# Per-platform downloader options (passed to yt-dlp).
# Instagram usually requires browser cookies.
# [platforms.instagram]
# cookies_from_browser = "chrome"     # or "firefox", "edge", ...
# cookies_file = "/path/to/cookies.txt"
#
# [platforms.tiktok]
# cookies_from_browser = "chrome"
"""
