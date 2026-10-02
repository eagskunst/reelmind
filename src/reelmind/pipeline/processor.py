"""Orchestrates download -> transcribe -> frames -> analyze -> store. No UI concerns here."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from reelmind.config import Config
from reelmind.llm import LLMClient
from reelmind.models import VideoRef
from reelmind.pipeline import media
from reelmind.pipeline.analyze import analyze
from reelmind.pipeline.transcribe import Transcriber, Transcript
from reelmind.platforms.base import PlatformRegistry, default_registry
from reelmind.storage import Storage


class Processor:
    def __init__(
        self,
        cfg: Config,
        storage: Storage,
        llm: LLMClient,
        transcriber: Transcriber,
        registry: PlatformRegistry | None = None,
    ) -> None:
        self.cfg = cfg
        self.storage = storage
        self.llm = llm
        self.transcriber = transcriber
        self.registry = registry or default_registry

    def enqueue(self, refs: list[VideoRef]) -> int:
        """Add refs to the queue. Returns number of newly added items."""
        return sum(1 for ref in refs if self.storage.add_pending(ref))

    def process_pending(
        self,
        retry_failed: bool = False,
        limit: int | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> dict[str, int]:
        """Process queued items. Returns counts {done, failed, skipped}."""
        counts = {"done": 0, "failed": 0, "skipped": 0}
        for row in self.storage.list_pending(retry_failed=retry_failed, limit=limit):
            self._emit(on_event, "start", row)
            if row["status"] == "done":
                counts["skipped"] += 1
                continue
            try:
                self._process_one(row)
            except Exception as e:  # noqa: BLE001 — keep processing other items
                self.storage.mark_failed(row["pk"], str(e))
                counts["failed"] += 1
                self._emit(on_event, "failed", row, error=str(e))
                continue
            counts["done"] += 1
            self._emit(on_event, "done", row)
        return counts

    def _process_one(self, row: Any) -> None:
        ref = VideoRef(platform=row["platform"], video_id=row["video_id"], url=row["url"])
        platform = self.registry.for_name(ref.platform)
        if platform is None:
            raise RuntimeError(f"no platform registered for {ref.platform!r}")

        workdir = self.cfg.cache_dir / ref.platform / _safe_id(ref.video_id)
        workdir.mkdir(parents=True, exist_ok=True)
        try:
            fetched = platform.download(ref, workdir, self.cfg)

            transcript = Transcript()
            frames: list[Path] = []
            if fetched.media_path is not None:
                frames = media.extract_frames(
                    fetched.media_path,
                    workdir / "frames",
                    count=self.cfg.frames.count,
                    max_width=self.cfg.frames.max_width,
                    max_count=self.cfg.frames.max_count,
                    seconds_per_frame=self.cfg.frames.seconds_per_frame,
                )
                audio = media.extract_audio(fetched.media_path, workdir / "audio.wav")
                if audio is not None:
                    transcript = self.transcriber.transcribe(audio)

            analysis, usage = analyze(fetched, transcript, frames, self.llm, self.cfg)
            self.storage.save_result(row["pk"], fetched, transcript.text, analysis)
            self.storage.record_usage(self.cfg.llm.model, "analyze", usage)
        finally:
            if not self.cfg.keep_media:
                shutil.rmtree(workdir, ignore_errors=True)

    @staticmethod
    def _emit(
        cb: Callable[[str, dict[str, Any]], None] | None,
        event: str,
        row: Any,
        **extra: Any,
    ) -> None:
        if cb:
            payload = {"pk": row["pk"], "url": row["url"], "platform": row["platform"], **extra}
            cb(event, payload)


def _safe_id(video_id: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in video_id)
