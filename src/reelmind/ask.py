"""Question answering: cheap plan -> storage search (with relaxation) -> grounded answer."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from reelmind.config import Config
from reelmind.llm import LLMClient, Usage
from reelmind.storage import Storage


class QueryPlan(BaseModel):
    categories: list[str] = Field(default_factory=list)
    city: str | None = None
    upcoming_only: bool = False
    date_from: str | None = None
    date_to: str | None = None
    keywords: list[str] = Field(default_factory=list)


@dataclass
class AskResult:
    answer: str
    video_ids: list[int] = field(default_factory=list)
    plan: QueryPlan | None = None
    relaxed: str | None = None  # e.g. "dropped keywords", "dropped city"
    usage: Usage = field(default_factory=Usage)


def _normalize_plan(data: dict[str, Any]) -> dict[str, Any]:
    """Small models return list fields as scalars; coerce before validation."""
    data = dict(data)
    for key in ("categories", "keywords"):
        value = data.get(key)
        if isinstance(value, str):
            data[key] = [value]
        elif value is not None and not isinstance(value, list):
            data[key] = []
    return data


def _home_city(cfg: Config) -> str | None:
    if not cfg.user.home_location:
        return None
    return cfg.user.home_location.split(",")[0].strip() or None


def _plan_messages(question: str, cfg: Config, today: date) -> list[dict[str, Any]]:
    home = cfg.user.home_location or "(not set)"
    system = f"""You convert a user question about their saved videos into a JSON search plan:
{{"categories": [...], "city": str|null, "upcoming_only": bool,
  "date_from": "YYYY-MM-DD"|null, "date_to": "YYYY-MM-DD"|null, "keywords": [...]}}

Valid categories: {", ".join(cfg.categories)}
Today: {today.isoformat()}
User's home location: {home}

Rules:
- "near me" / "nearby" / no explicit city -> city = the city part of home location
  (currently: {_home_city(cfg) or "unknown — leave city null"}).
- upcoming_only = true when the question is about future/current events.
- keywords: a few meaningful search words (foods, names, vibes). Empty list is fine.
- Output ONLY the JSON object."""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": question},
    ]


def _compact(video: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": video["id"],
        "platform": video["platform"],
        "category": video["category"],
        "title": video["title"],
        "summary": video["summary"],
        "post_date": video["upload_date"],
        "url": video["url"],
        "places": video["places"],
        "events": video["events"],
        "has_undated_event": video.get("has_undated_event", False),
    }


def _answer_messages(
    question: str, candidates: list[dict[str, Any]], relaxed: str | None, cfg: Config
) -> list[dict[str, Any]]:
    note = ""
    if relaxed == "keywords":
        note = (
            "\nNote: the keyword filter matched nothing, so results were broadened "
            "— say so briefly if relevant."
        )
    elif relaxed == "city":
        note = (
            "\nNote: nothing matched in the requested city; these results are from "
            "elsewhere — say so plainly."
        )
    system = f"""You answer questions about the user's saved-video collection using ONLY
the candidate records provided below. Never invent places, events or links.
- Answer in "{cfg.user.summary_language}", in simple language.
- Give a short list: name/title, why it fits, and the video link.
- If nothing matches, say so plainly and suggest what the collection does have.{note}"""
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": (
                f"Question: {question}\n\nCandidates:\n{json.dumps(candidates, ensure_ascii=False)}"
            ),
        },
    ]


def ask(
    question: str,
    cfg: Config,
    storage: Storage,
    llm: LLMClient,
    today: date | None = None,
) -> AskResult:
    today = today or date.today()
    total = Usage()

    # Step 1: cheap planning call.
    plan_data, u = llm.chat_json(cfg.llm.model, _plan_messages(question, cfg, today))
    total.prompt_tokens += u.prompt_tokens
    total.completion_tokens += u.completion_tokens
    plan = QueryPlan.model_validate(_normalize_plan(plan_data))
    storage.record_usage(cfg.llm.model, "plan", u)

    # Step 2: search with relaxation.
    relaxed = None

    def run(p: QueryPlan) -> list[dict[str, Any]]:
        return storage.search(
            categories=p.categories or None,
            city=p.city,
            upcoming_only=p.upcoming_only,
            today=today,
            keywords=p.keywords or None,
            date_from=p.date_from,
            date_to=p.date_to,
            match_any=True,  # planner keywords are recall hints, OR them
        )

    candidates = run(plan)
    if not candidates and plan.keywords:
        relaxed = "keywords"
        plan2 = plan.model_copy(update={"keywords": []})
        candidates = run(plan2)
        plan = plan2
    if not candidates and plan.city:
        relaxed = "city"
        plan = plan.model_copy(update={"city": None})
        candidates = run(plan)

    if not candidates:
        # deterministic empty path — don't let the model hallucinate on []
        return AskResult(
            answer=(
                "Nothing in your saved videos matches that question yet. "
                "Try adding more videos or broadening the question."
            ),
            plan=plan,
            relaxed=relaxed,
            usage=total,
        )

    compact = [_compact(v) for v in candidates]

    # Step 3: grounded answer.
    text, u = llm.chat_text(
        cfg.llm.answer_model_name, _answer_messages(question, compact, relaxed, cfg)
    )
    total.prompt_tokens += u.prompt_tokens
    total.completion_tokens += u.completion_tokens
    storage.record_usage(cfg.llm.answer_model_name, "answer", u)

    return AskResult(
        answer=text,
        video_ids=[v["id"] for v in candidates],
        plan=plan,
        relaxed=relaxed,
        usage=total,
    )
