from reelmind.ask import QueryPlan, ask
from reelmind.config import UserConfig
from reelmind.models import Analysis, FetchedVideo, VideoRef

from .conftest import valid_analysis_dict


def seed(storage, vid="1", city="Madrid"):
    storage.add_pending(VideoRef(platform="tiktok", video_id=vid, url=f"https://x/{vid}"))
    pk = storage.list_pending()[0]["pk"]
    a = Analysis.model_validate(valid_analysis_dict(places=[{"name": "Ramen-Ya", "city": city}]))
    storage.save_result(
        pk,
        FetchedVideo(ref=VideoRef(platform="tiktok", video_id=vid, url=f"https://x/{vid}")),
        "t",
        a,
    )


def test_ask_plan_search_answer(cfg, storage, fake_llm):
    seed(storage)
    fake_llm.json_responses = [
        {"categories": ["restaurant"], "city": "Madrid", "keywords": ["ramen"]}
    ]
    fake_llm.text_responses = ["Go to Ramen-Ya! https://x/1"]
    result = ask("what restaurant can I go to eat?", cfg, storage, fake_llm)
    assert result.answer == "Go to Ramen-Ya! https://x/1"
    assert result.video_ids
    assert result.relaxed is None
    # planning call was made with the cheap model
    assert len(fake_llm.json_calls) == 1


def test_ask_relaxation_drops_keywords(cfg, storage, fake_llm):
    seed(storage)
    fake_llm.json_responses = [
        {"categories": ["restaurant"], "city": "Madrid", "keywords": ["nonexistentdish"]}
    ]
    result = ask("restaurants?", cfg, storage, fake_llm)
    assert result.relaxed == "keywords"
    assert result.video_ids  # found after dropping keywords


def test_ask_relaxation_drops_city(cfg, storage, fake_llm):
    seed(storage, city="Madrid")
    fake_llm.json_responses = [{"categories": ["restaurant"], "city": "Berlin", "keywords": []}]
    result = ask("restaurants in berlin?", cfg, storage, fake_llm)
    assert result.relaxed == "city"
    assert result.video_ids


def test_ask_near_me_uses_home_location(cfg, storage, fake_llm):
    cfg.user = UserConfig(home_location="Madrid, Spain")
    seed(storage)
    fake_llm.json_responses = [{"categories": ["restaurant"], "city": "Madrid"}]
    ask("what's near me?", cfg, storage, fake_llm)
    plan_prompt = fake_llm.json_calls[0][0]["content"]
    assert "Madrid" in plan_prompt


def test_query_plan_defaults():
    p = QueryPlan.model_validate({})
    assert p.categories == [] and p.upcoming_only is False and p.city is None
