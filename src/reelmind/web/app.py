"""FastAPI app factory — dependencies injected so tests can use fakes."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from reelmind.ask import ask as run_ask
from reelmind.config import Config
from reelmind.llm import LLMClient
from reelmind.pipeline.processor import Processor
from reelmind.platforms import default_registry
from reelmind.storage import Storage

STATIC_DIR = Path(__file__).parent / "static"


class AskBody(BaseModel):
    question: str


class AddBody(BaseModel):
    urls: list[str]


def create_app(
    cfg: Config,
    storage: Storage,
    processor: Processor,
    llm: LLMClient,
) -> FastAPI:
    app = FastAPI(title="reelmind")
    lock = threading.Lock()
    worker: dict[str, threading.Thread | None] = {"t": None}

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/videos")
    def list_videos(
        category: str | None = None,
        q: str | None = None,
        city: str | None = None,
        upcoming: bool = False,
    ) -> list[dict[str, Any]]:
        return storage.search(
            categories=[category] if category else None,
            city=city or None,
            upcoming_only=upcoming,
            keywords=[q] if q else None,
            limit=200,
        )

    @app.get("/api/videos/{video_id}")
    def get_video(video_id: int) -> dict[str, Any]:
        v = storage.get(video_id)
        if v is None:
            from fastapi import HTTPException

            raise HTTPException(404, "not found")
        return v

    @app.post("/api/ask")
    def ask(body: AskBody) -> dict[str, Any]:
        with lock:
            result = run_ask(body.question, cfg, storage, llm)
        return {"answer": result.answer, "video_ids": result.video_ids, "relaxed": result.relaxed}

    @app.post("/api/add")
    def add(body: AddBody) -> dict[str, Any]:
        refs = []
        for url in body.urls:
            url = url.strip()
            if not url:
                continue
            platform = default_registry.for_url(url)
            if platform is None:
                continue
            ref = platform.parse(url)
            if ref is not None:
                refs.append(ref)
        new = processor.enqueue(refs)

        def work() -> None:
            try:
                processor.process_pending()
            finally:
                worker["t"] = None

        t = worker.get("t")
        if t is None or not t.is_alive():
            worker["t"] = threading.Thread(target=work, daemon=True)
            worker["t"].start()  # type: ignore[union-attr]
        return {"enqueued": new, "queued": len(refs)}

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        rows = storage.list_pending()
        failed = storage.list_pending(retry_failed=True)
        return {"pending": len(rows), "failed": len(failed) - len(rows)}

    return app
