"""Tests for the second-round fixes: canonical merge, playlist info, match_any, ordering."""

from datetime import date
from pathlib import Path

from reelmind.models import Analysis, Event, FetchedVideo, VideoRef
from reelmind.pipeline.processor import Processor
from reelmind.platforms.ytdlp import YtDlpPlatform

from .conftest import FakePlatform, FakeTranscriber, valid_analysis_dict


def save(storage, vid: str, analysis: Analysis, platform: str = "tiktok") -> int:
    storage.add_pending(VideoRef(platform=platform, video_id=vid, url=f"https://x/{vid}"))
    pk = next(r["pk"] for r in storage.list_pending() if r["video_id"] == vid)
    fetched = FetchedVideo(ref=VideoRef(platform=platform, video_id=vid, url=f"https://x/{vid}"))
    storage.save_result(pk, fetched, "t", analysis)
    return pk


# --- fix 1: canonical-id merge on save ----------------------------------------


def test_save_result_merges_short_ref(storage):
    canon_pk = save(storage, "7234", Analysis(category="restaurant", title="canon"))
    # a pending short-link row that resolves to the same canonical id
    storage.add_pending(
        VideoRef(platform="tiktok", video_id="short-abc", url="https://vm.tiktok.com/abc/")
    )
    short_pk = next(r["pk"] for r in storage.list_pending())
    fetched = FetchedVideo(ref=VideoRef(platform="tiktok", video_id="7234", url="https://x/7234"))
    storage.save_result(short_pk, fetched, "t", Analysis(category="cafe_bar", title="updated"))
    rows = storage.search(done_only=False)
    assert len(rows) == 1
    assert rows[0]["id"] == canon_pk  # merged onto the existing row
    assert rows[0]["status"] == "done"
    assert rows[0]["title"] == "updated"


def test_processor_short_ref_merges(cfg, storage, fake_llm, registry):
    # canonical already done; a short ref resolves to the same id
    platform = FakePlatform(canonical_map={"short-abc": "7234"})
    registry.register(platform)
    proc = Processor(cfg, storage, fake_llm, FakeTranscriber(), registry)
    fake_llm.json_responses = [valid_analysis_dict()]
    proc.enqueue([VideoRef(platform="fake", video_id="7234", url="https://fake.example/v/7234")])
    proc.process_pending()
    fake_llm.json_responses = [valid_analysis_dict()]
    proc.enqueue(
        [VideoRef(platform="fake", video_id="short-abc", url="https://fake.example/v/short-abc")]
    )
    counts = proc.process_pending()
    assert counts == {"done": 1, "failed": 0, "skipped": 0}
    rows = storage.search(done_only=False)
    assert len(rows) == 1 and rows[0]["status"] == "done"


# --- fix 2: playlist/entries info ---------------------------------------------


class FakeYdl:
    def __init__(self, mapping: dict[str, Path] | None = None) -> None:
        self.mapping = mapping or {}

    def prepare_filename(self, entry: dict) -> str:
        return str(self.mapping.get(str(entry.get("id")), Path("/nonexistent")))


class DummyPlatform(YtDlpPlatform):
    name = "dummy"

    def matches(self, url: str) -> bool:
        return True

    def parse(self, url: str):
        return None


def test_pick_entry_prefers_downloaded(tmp_path: Path):
    p = DummyPlatform()
    f = tmp_path / "entry2.mp4"
    f.write_bytes(b"x")
    info = {
        "_type": "playlist",
        "id": "pl",
        "title": "carousel",
        "uploader": "bob",
        "entries": [
            {"id": "e1", "requested_downloads": [{"filepath": str(tmp_path / "e1.mp4")}]},
            {"id": "e2", "requested_downloads": [{"filepath": str(f)}]},
        ],
    }
    entry = p._pick_entry(FakeYdl(), info, tmp_path)
    assert entry is not None and entry["id"] == "e2"
    fetched = p._to_fetched(info, f, VideoRef(platform="dummy", video_id="x", url="u"), entry)
    assert fetched.title == "carousel"  # top-level kept
    assert fetched.author == "bob"
    assert fetched.media_path == f


def test_pick_entry_top_level_fields_fallback(tmp_path: Path):
    p = DummyPlatform()
    f = tmp_path / "e1.mp4"
    f.write_bytes(b"x")
    info = {
        "_type": "playlist",
        "entries": [
            {"id": "e1", "title": "entry title", "requested_downloads": [{"filepath": str(f)}]}
        ],
    }
    entry = p._pick_entry(FakeYdl(), info, tmp_path)
    fetched = p._to_fetched(info, f, VideoRef(platform="dummy", video_id="x", url="u"), entry)
    assert fetched.title == "entry title"  # fell back to entry


def test_with_hint(cfg):
    p = DummyPlatform()
    e = p._with_hint(RuntimeError("login required"), cfg)
    assert "dummy may require cookies" in str(e)
    e2 = p._with_hint(RuntimeError("unrelated failure"), cfg)
    assert str(e2) == "unrelated failure"


# --- fix 4: match_any keyword semantics ---------------------------------------


def test_match_any_or_semantics(storage):
    save(storage, "1", Analysis(title="ramen place", summary="noodles"))
    save(storage, "2", Analysis(title="sushi spot", summary="fish"))
    # AND (default): no video matches both
    assert storage.search(keywords=["ramen", "sushi"]) == []
    # OR: both match
    res = storage.search(keywords=["ramen", "sushi"], match_any=True)
    assert len(res) == 2


# --- fix 5: upcoming ordering --------------------------------------------------


def test_upcoming_ordering(storage):
    today = date(2026, 10, 2)
    save(storage, "a", Analysis(events=[Event(name="later", start_date="2026-12-01")]))
    save(storage, "b", Analysis(events=[Event(name="undated")]))
    save(storage, "c", Analysis(events=[Event(name="sooner", start_date="2026-10-20")]))
    res = storage.search(upcoming_only=True, today=today)
    names = [r["events"][0]["name"] for r in res]
    assert names == ["sooner", "later", "undated"]
