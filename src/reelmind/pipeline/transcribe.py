"""Transcription backends: local faster-whisper (free), OpenAI-compatible API, or none."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from reelmind.config import Config, TranscriptionConfig


class Transcript(BaseModel):
    text: str = ""
    language: str | None = None


class Transcriber(Protocol):
    def transcribe(self, audio_path: Path) -> Transcript: ...


class NoopTranscriber:
    def transcribe(self, audio_path: Path) -> Transcript:
        return Transcript()


class FasterWhisperTranscriber:
    """Local whisper via faster-whisper. Model loaded lazily and cached."""

    _model_cache: dict[tuple[str, str, str], object] = {}

    def __init__(self, cfg: TranscriptionConfig) -> None:
        self.cfg = cfg

    def _model(self) -> object:
        key = (self.cfg.model, self.cfg.device, self.cfg.compute_type)
        if key not in self._model_cache:
            from faster_whisper import WhisperModel

            self._model_cache[key] = WhisperModel(
                self.cfg.model,
                device=self.cfg.device,
                compute_type=self.cfg.compute_type,
            )
        return self._model_cache[key]

    def transcribe(self, audio_path: Path) -> Transcript:
        model = self._model()
        segments, info = model.transcribe(str(audio_path), vad_filter=True)  # type: ignore[attr-defined]
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return Transcript(text=text, language=getattr(info, "language", None))


class OpenAITranscriber:
    """Whisper via any OpenAI-compatible audio.transcriptions endpoint."""

    def __init__(self, cfg: Config) -> None:
        from openai import OpenAI

        headers = _openrouter_headers(cfg.llm.base_url)
        self._client = OpenAI(
            base_url=cfg.llm.base_url,
            api_key=cfg.llm.api_key(),
            default_headers=headers or None,
        )
        self._model = cfg.transcription.model

    def transcribe(self, audio_path: Path) -> Transcript:
        with audio_path.open("rb") as f:
            resp = self._client.audio.transcriptions.create(model=self._model, file=f)
        return Transcript(text=getattr(resp, "text", "") or "", language=None)


def _openrouter_headers(base_url: str) -> dict[str, str]:
    if "openrouter.ai" in base_url:
        return {"HTTP-Referer": "https://github.com/eagskunst/reelmind", "X-Title": "reelmind"}
    return {}


def build_transcriber(cfg: Config) -> Transcriber:
    backend = cfg.transcription.backend
    if backend == "faster-whisper":
        return FasterWhisperTranscriber(cfg.transcription)
    if backend == "openai":
        return OpenAITranscriber(cfg)
    return NoopTranscriber()
