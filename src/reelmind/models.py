"""Core models. `Analysis` is the LLM output contract — all optional fields have defaults."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


class VideoRef(BaseModel):
    platform: str
    video_id: str
    url: str


class FetchedVideo(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    ref: VideoRef
    title: str = ""
    description: str = ""
    author: str = ""
    upload_date: str | None = None  # ISO date
    duration: float | None = None
    media_path: Path | None = None  # downloaded file; None for photo carousels with only images
    raw_meta: dict[str, Any] = Field(default_factory=dict)


_EMPTY_STRINGS = {"", "null", "none", "unknown", "n/a"}
_ISO_DATE = r"^\d{4}-\d{2}-\d{2}$"


def _clean_str(value: Any) -> Any:
    """LLMs emit "unknown"/""/null-ish strings for missing fields -> normalize to None."""
    if isinstance(value, str):
        value = value.strip()
        if value.lower() in _EMPTY_STRINGS:
            return None
    return value


class Place(BaseModel):
    name: str
    kind: str | None = None  # e.g. cuisine / place type
    address: str | None = None
    city: str | None = None
    country: str | None = None
    price_range: str | None = None
    notes: str | None = None

    @field_validator("kind", "address", "city", "country", "price_range", "notes", mode="before")
    @classmethod
    def _str_or_none(cls, v: Any) -> Any:
        return _clean_str(v)


class Event(BaseModel):
    name: str
    venue: str | None = None
    city: str | None = None
    start_date: str | None = None  # ISO date
    end_date: str | None = None
    time: str | None = None
    price: str | None = None
    notes: str | None = None

    @field_validator(
        "venue", "city", "start_date", "end_date", "time", "price", "notes", mode="before"
    )
    @classmethod
    def _str_or_none(cls, v: Any, info: ValidationInfo) -> Any:
        v = _clean_str(v)
        # dates must be ISO or storage's string comparisons break
        if info.field_name in ("start_date", "end_date") and isinstance(v, str):
            if not re.match(_ISO_DATE, v):
                return None
        return v


class Analysis(BaseModel):
    """LLM output contract. All fields have defaults so partial JSON still validates."""

    category: str = "other"
    title: str = ""
    summary: str = ""  # 2-4 plain sentences
    key_points: list[str] = Field(default_factory=list)
    places: list[Place] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    language: str = "en"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
