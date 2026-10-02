from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from reelmind.config import Config
from reelmind.llm import Usage
from reelmind.models import FetchedVideo, VideoRef
from reelmind.pipeline.transcribe import Transcript
from reelmind.platforms.base import Platform, PlatformRegistry
from reelmind.storage import Storage


class FakeLLM:
    """Scriptable fake LLMClient. json_responses: queue of dicts (or Exceptions to raise)."""

    def __init__(self) -> None:
        self.json_responses: list[Any] = []
        self.text_responses: list[str] = ["fake answer"]
        self.json_calls: list[list[dict]] = []
        self.text_calls: list[list[dict]] = []

    def chat_json(self, model: str, messages: list[dict]) -> tuple[dict, Usage]:
        self.json_calls.append(messages)
        item = self.json_responses.pop(0) if self.json_responses else {}
        if isinstance(item, Exception):
            raise item
        return item, Usage(prompt_tokens=10, completion_tokens=20)

    def chat_text(self, model: str, messages: list[dict]) -> tuple[str, Usage]:
        self.text_calls.append(messages)
        text = self.text_responses.pop(0) if self.text_responses else "fake answer"
        return text, Usage(prompt_tokens=5, completion_tokens=7)


class FakeTranscriber:
    def __init__(self, text: str = "fake transcript", language: str = "en") -> None:
        self.text = text
        self.language = language
        self.calls: list[Path] = []

    def transcribe(self, audio_path: Path) -> Transcript:
        self.calls.append(audio_path)
        return Transcript(text=self.text, language=self.language)


class FakePlatform(Platform):
    name = "fake"

    def __init__(
        self, fetched: FetchedVideo | None = None, fail_on: set[str] | None = None
    ) -> None:
        self.fetched = fetched
        self.fail_on = fail_on or set()
        self.downloads: list[str] = []

    def matches(self, url: str) -> bool:
        return "fake.example" in url

    def parse(self, url: str) -> VideoRef | None:
        if not self.matches(url):
            return None
        return VideoRef(platform=self.name, video_id=url.rstrip("/").rsplit("/", 1)[-1], url=url)

    def download(self, ref: VideoRef, workdir: Path, cfg: Config) -> FetchedVideo:
        self.downloads.append(ref.url)
        if ref.url in self.fail_on:
            raise RuntimeError("boom")
        if self.fetched is not None:
            return self.fetched
        media = workdir / "media.mp4"
        media.write_bytes(b"")
        return FetchedVideo(
            ref=ref, title="fake video", description="desc", author="someone", media_path=media
        )


@pytest.fixture()
def cfg(tmp_path: Path) -> Config:
    return Config(data_dir=tmp_path / "data")


@pytest.fixture()
def storage(tmp_path: Path) -> Storage:
    return Storage(tmp_path / "test.db")


@pytest.fixture()
def registry() -> PlatformRegistry:
    return PlatformRegistry()


@pytest.fixture()
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture()
def fake_platform() -> FakePlatform:
    return FakePlatform()


ANALYSIS_JSON = {
    "category": "restaurant",
    "title": "Great ramen spot",
    "summary": "A ramen place in Madrid. Cheap and popular.",
    "key_points": ["cash only"],
    "places": [
        {
            "name": "Ramen-Ya",
            "kind": "ramen restaurant",
            "address": "Calle Mayor 1",
            "city": "Madrid",
            "country": "Spain",
            "price_range": "€",
        }
    ],
    "events": [],
    "tags": ["ramen", "madrid"],
    "language": "en",
    "confidence": 0.9,
}


def valid_analysis_dict(**overrides: Any) -> dict:
    d = dict(ANALYSIS_JSON)
    d.update(overrides)
    return d
