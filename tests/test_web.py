import pytest
from fastapi.testclient import TestClient

from reelmind.pipeline.processor import Processor
from reelmind.web.app import create_app

from .conftest import FakeTranscriber, valid_analysis_dict


@pytest.fixture()
def client(cfg, storage, fake_llm, registry, fake_platform):
    registry.register(fake_platform)
    proc = Processor(cfg, storage, fake_llm, FakeTranscriber(), registry)
    return TestClient(create_app(cfg, storage, proc, fake_llm))


def test_index(client):
    res = client.get("/")
    assert res.status_code == 200
    assert b"reelmind" in res.content


def test_ask(client, fake_llm):
    fake_llm.json_responses = [{"categories": []}]
    fake_llm.text_responses = ["nothing saved yet"]
    res = client.post("/api/ask", json={"question": "hi"})
    assert res.status_code == 200
    assert res.json()["answer"] == "nothing saved yet"


def test_videos_filters(client, storage):
    from reelmind.models import Analysis, FetchedVideo, VideoRef

    storage.add_pending(VideoRef(platform="tiktok", video_id="1", url="u1"))
    pk = storage.list_pending()[0]["pk"]
    storage.save_result(
        pk,
        FetchedVideo(ref=VideoRef(platform="tiktok", video_id="1", url="u1")),
        "t",
        Analysis.model_validate(valid_analysis_dict()),
    )
    res = client.get("/api/videos", params={"category": "restaurant"})
    assert res.status_code == 200 and len(res.json()) == 1
    res = client.get("/api/videos", params={"category": "event"})
    assert res.json() == []
    res = client.get("/api/videos", params={"q": "ramen"})
    assert len(res.json()) == 1
    res = client.get("/api/videos", params={"city": "madrid"})
    assert len(res.json()) == 1
    vid = res.json()[0]["id"]
    assert client.get(f"/api/videos/{vid}").status_code == 200
    assert client.get("/api/videos/9999").status_code == 404


def test_add_enqueues(client, storage):
    res = client.post(
        "/api/add", json={"urls": ["https://www.tiktok.com/@a/video/123", "https://nope.com/x", ""]}
    )
    assert res.status_code == 200
    assert res.json()["queued"] == 1


def test_status(client):
    res = client.get("/api/status")
    assert res.status_code == 200
    assert "pending" in res.json() and "failed" in res.json()
