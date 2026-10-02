import json
from datetime import date

import pytest
from pydantic import ValidationError

from reelmind.models import Analysis, FetchedVideo, VideoRef
from reelmind.pipeline.analyze import analyze, build_messages
from reelmind.pipeline.transcribe import Transcript

from .conftest import valid_analysis_dict


def fetched() -> FetchedVideo:
    return FetchedVideo(
        ref=VideoRef(platform="tiktok", video_id="1", url="u"),
        title="cap",
        description="desc #food",
        author="bob",
        upload_date="2026-09-01",
    )


def test_valid_json_to_analysis(cfg, fake_llm):
    fake_llm.json_responses = [valid_analysis_dict()]
    analysis, usage = analyze(fetched(), Transcript(text="hi"), [], fake_llm, cfg)
    assert analysis.category == "restaurant"
    assert analysis.places[0].name == "Ramen-Ya"
    assert usage.prompt_tokens == 10


def test_retry_on_invalid(cfg, fake_llm):
    fake_llm.json_responses = [{"category": 123, "confidence": "nope"}, valid_analysis_dict()]
    analysis, _ = analyze(fetched(), Transcript(), [], fake_llm, cfg)
    assert analysis.title == "Great ramen spot"
    assert len(fake_llm.json_calls) == 2
    # second call includes the validation error feedback
    last = fake_llm.json_calls[1][-1]["content"]
    assert "did not validate" in last


def test_double_failure_raises(cfg, fake_llm):
    fake_llm.json_responses = [{"confidence": "x"}, {"confidence": "y"}]
    with pytest.raises(ValidationError):
        analyze(fetched(), Transcript(), [], fake_llm, cfg)


def test_unknown_category_becomes_other(cfg, fake_llm):
    fake_llm.json_responses = [valid_analysis_dict(category="underwater_basket_weaving")]
    analysis, _ = analyze(fetched(), Transcript(), [], fake_llm, cfg)
    assert analysis.category == "other"


def test_frames_sent_as_image_parts(cfg, fake_llm, tmp_path):
    frame = tmp_path / "f.jpg"
    frame.write_bytes(b"\xff\xd8fake-jpeg")
    msgs = build_messages(fetched(), Transcript(text="t"), [frame], cfg, today=date(2026, 10, 2))
    content = msgs[1]["content"]
    images = [c for c in content if c["type"] == "image_url"]
    assert len(images) == 1
    assert images[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    # text part carries context
    text = next(c["text"] for c in content if c["type"] == "text")
    assert "2026-10-02" in text and "bob" in text


def test_system_prompt_has_schema_and_categories(cfg):
    msgs = build_messages(fetched(), Transcript(), [], cfg)
    system = msgs[0]["content"]
    assert json.dumps(Analysis.model_json_schema())[:50] in system[:5000] or "schema" in system
    assert "restaurant" in system and "never invent" in system.lower()
