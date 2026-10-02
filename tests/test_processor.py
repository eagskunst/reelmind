from reelmind.models import FetchedVideo, VideoRef
from reelmind.pipeline.processor import Processor

from .conftest import FakePlatform, FakeTranscriber, valid_analysis_dict


def make(cfg, storage, fake_llm, registry, platform) -> Processor:
    registry.register(platform)
    return Processor(cfg, storage, fake_llm, FakeTranscriber(), registry)


def refs(*ids: str) -> list[VideoRef]:
    return [VideoRef(platform="fake", video_id=i, url=f"https://fake.example/v/{i}") for i in ids]


def test_end_to_end(cfg, storage, fake_llm, registry, fake_platform):
    fake_llm.json_responses = [valid_analysis_dict()]
    proc = make(cfg, storage, fake_llm, registry, fake_platform)
    assert proc.enqueue(refs("1")) == 1
    counts = proc.process_pending()
    assert counts == {"done": 1, "failed": 0, "skipped": 0}
    v = storage.get(1)
    assert v["status"] == "done"
    assert v["title"] == "Great ramen spot"
    assert v["places"][0]["name"] == "Ramen-Ya"
    # media deleted (keep_media=False)
    assert not list(cfg.cache_dir.rglob("media.*"))


def test_done_skipped(cfg, storage, fake_llm, registry, fake_platform):
    fake_llm.json_responses = [valid_analysis_dict()]
    proc = make(cfg, storage, fake_llm, registry, fake_platform)
    proc.enqueue(refs("1"))
    proc.process_pending()
    # second run: nothing pending -> no more downloads
    counts = proc.process_pending()
    assert counts == {"done": 0, "failed": 0, "skipped": 0}
    assert len(fake_platform.downloads) == 1


def test_failure_marks_failed_and_continues(cfg, storage, fake_llm, registry):
    platform = FakePlatform(fail_on={"https://fake.example/v/bad"})
    fake_llm.json_responses = [valid_analysis_dict()]
    proc = make(cfg, storage, fake_llm, registry, platform)
    proc.enqueue(refs("bad", "good"))
    counts = proc.process_pending()
    assert counts == {"done": 1, "failed": 1, "skipped": 0}
    rows = storage.search(done_only=False)
    by_url = {r["url"]: r for r in rows}
    assert by_url["https://fake.example/v/bad"]["status"] == "failed"
    assert "boom" in by_url["https://fake.example/v/bad"]["error"]
    assert by_url["https://fake.example/v/good"]["status"] == "done"


def test_retry_failed(cfg, storage, fake_llm, registry, fake_platform):
    platform = FakePlatform(fail_on={"https://fake.example/v/x"})
    proc = make(cfg, storage, fake_llm, registry, platform)
    proc.enqueue(refs("x"))
    proc.process_pending()
    # fix the platform and retry
    platform.fail_on = set()
    fake_llm.json_responses = [valid_analysis_dict()]
    counts = proc.process_pending(retry_failed=True)
    assert counts["done"] == 1


def test_limit(cfg, storage, fake_llm, registry, fake_platform):
    fake_llm.json_responses = [valid_analysis_dict()]
    proc = make(cfg, storage, fake_llm, registry, fake_platform)
    proc.enqueue(refs("1", "2", "3"))
    counts = proc.process_pending(limit=1)
    assert counts["done"] == 1
    assert len(fake_platform.downloads) == 1


def test_no_media_path_transcript_empty(cfg, storage, fake_llm, registry, tmp_path):
    fetched = FetchedVideo(
        ref=VideoRef(platform="fake", video_id="1", url="https://fake.example/v/1"),
        media_path=None,
    )
    platform = FakePlatform(fetched=fetched)
    tr = FakeTranscriber()
    registry.register(platform)
    fake_llm.json_responses = [valid_analysis_dict()]
    proc = Processor(cfg, storage, fake_llm, tr, registry)
    proc.enqueue(refs("1"))
    counts = proc.process_pending()
    assert counts["done"] == 1
    assert tr.calls == []  # no audio -> transcriber not invoked
