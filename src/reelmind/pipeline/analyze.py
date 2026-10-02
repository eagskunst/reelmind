"""Build the analysis prompt and validate LLM output into an Analysis."""

from __future__ import annotations

import base64
import json
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from reelmind.config import Config
from reelmind.llm import LLMClient, Message, Usage
from reelmind.models import Analysis, FetchedVideo
from reelmind.pipeline.transcribe import Transcript

MAX_TRANSCRIPT_CHARS = 6000


def _frame_part(path: Path) -> dict[str, Any]:
    b64 = base64.b64encode(path.read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}


def build_messages(
    fetched: FetchedVideo,
    transcript: Transcript,
    frame_paths: list[Path],
    cfg: Config,
    today: date | None = None,
) -> list[Message]:
    today = today or date.today()
    schema = json.dumps(Analysis.model_json_schema())
    system = f"""You analyze short social-media videos saved by the user (TikTok/Instagram/YouTube).
Extract structured information and output ONLY a JSON object matching this schema:
{schema}

Categories (pick exactly one): {", ".join(cfg.categories)}

Rules:
- Write the summary in language "{cfg.user.summary_language}" in 2-4 simple sentences,
  as if explaining to a friend.
- Never invent addresses, dates, prices or names. If unknown, use null.
- Extract EVERY distinct place and event mentioned — including ones only shown as
  on-screen text in the frames.
- For event dates without a year, infer the year from the post date.
- key_points: short practical facts (opening hours, what to order, ticket info, location hints)."""

    user_text = f"""Platform: {fetched.ref.platform}
Author: {fetched.author or "unknown"}
Post date: {fetched.upload_date or "unknown"}
Today's date: {today.isoformat()}
Caption/title: {fetched.title or "(none)"}
Description + hashtags:
{fetched.description or "(none)"}

Transcript (may be empty):
{transcript.text[:MAX_TRANSCRIPT_CHARS] or "(no transcript)"}"""

    content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
    for frame in frame_paths:
        content.append(_frame_part(frame))
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": content},
    ]


def _coerce_category(analysis: Analysis, cfg: Config) -> Analysis:
    if analysis.category not in cfg.categories:
        analysis.category = "other"
    return analysis


def analyze(
    fetched: FetchedVideo,
    transcript: Transcript,
    frame_paths: list[Path],
    llm: LLMClient,
    cfg: Config,
    today: date | None = None,
) -> tuple[Analysis, Usage]:
    """One LLM call -> validated Analysis. On failure, retry once with the error appended."""
    messages = build_messages(fetched, transcript, frame_paths, cfg, today)
    total = Usage()
    data, usage = llm.chat_json(cfg.llm.model, messages)
    total.prompt_tokens += usage.prompt_tokens
    total.completion_tokens += usage.completion_tokens
    try:
        return _coerce_category(Analysis.model_validate(data), cfg), total
    except ValidationError as e:
        messages.append(
            {
                "role": "user",
                "content": (
                    "Your previous JSON did not validate. Fix it and output ONLY the corrected "
                    f"JSON object.\nValidation error:\n{e}"
                ),
            }
        )
        data, usage = llm.chat_json(cfg.llm.model, messages)
        total.prompt_tokens += usage.prompt_tokens
        total.completion_tokens += usage.completion_tokens
        analysis = Analysis.model_validate(data)  # raises on second failure
        return _coerce_category(analysis, cfg), total
