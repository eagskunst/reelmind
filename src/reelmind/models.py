"""Core models. `Analysis` is the LLM output contract — all optional fields have defaults."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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


class Place(BaseModel):
    name: str
    kind: str | None = None  # e.g. cuisine / place type
    address: str | None = None
    city: str | None = None
    country: str | None = None
    price_range: str | None = None
    notes: str | None = None


class Event(BaseModel):
    name: str
    venue: str | None = None
    city: str | None = None
    start_date: str | None = None  # ISO date
    end_date: str | None = None
    time: str | None = None
    price: str | None = None
    notes: str | None = None


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
