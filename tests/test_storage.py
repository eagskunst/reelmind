from datetime import date

from reelmind.models import Analysis, Event, FetchedVideo, Place, VideoRef

from .conftest import ANALYSIS_JSON


def make_fetched(platform: str = "tiktok", vid: str = "1", url: str | None = None) -> FetchedVideo:
    return FetchedVideo(
        ref=VideoRef(platform=platform, video_id=vid, url=url or f"https://x/{vid}"),
        title="t",
        description="d",
        author="a",
    )


def save(storage, vid: str, analysis: Analysis) -> int:
    storage.add_pending(VideoRef(platform="tiktok", video_id=vid, url=f"https://x/{vid}"))
    pk = storage.list_pending()[0]["pk"]
    storage.save_result(pk, make_fetched(vid=vid), "transcript", analysis)
    return pk


def test_add_pending_and_transitions(storage):
    ref = VideoRef(platform="tiktok", video_id="1", url="u")
    assert storage.add_pending(ref) is True
    assert storage.add_pending(ref) is False  # dedupe
    rows = storage.list_pending()
    assert len(rows) == 1 and rows[0]["status"] == "pending"

    storage.mark_failed(rows[0]["pk"], "oops")
    assert storage.list_pending() == []
    assert len(storage.list_pending(retry_failed=True)) == 1
    assert storage.get(rows[0]["pk"])["error"] == "oops"

    save(storage, "2", Analysis.model_validate(ANALYSIS_JSON))
    assert storage.list_pending() == []


def test_save_result_and_resave_rebuilds_flat(storage):
    pk = save(storage, "1", Analysis.model_validate(ANALYSIS_JSON))
    v = storage.get(pk)
    assert v["status"] == "done"
    assert v["places"][0]["name"] == "Ramen-Ya"

    # re-save with a different analysis -> places replaced, not appended
    a2 = Analysis(category="event", title="t2", places=[Place(name="Cafe X")])
    storage.save_result(pk, make_fetched(vid="1"), "t", a2)
    v = storage.get(pk)
    assert [p["name"] for p in v["places"]] == ["Cafe X"]
    assert v["category"] == "event"


def test_search_category(storage):
    save(storage, "1", Analysis(category="restaurant", title="a"))
    save(storage, "2", Analysis(category="recipe", title="b"))
    res = storage.search(categories=["restaurant"])
    assert len(res) == 1 and res[0]["title"] == "a"


def test_search_city(storage):
    save(storage, "1", Analysis.model_validate(ANALYSIS_JSON))  # Madrid
    save(
        storage,
        "2",
        Analysis(category="restaurant", title="other", places=[Place(name="X", city="Lisbon")]),
    )
    res = storage.search(city="madrid")
    assert len(res) == 1 and res[0]["places"][0]["city"] == "Madrid"
    # case-insensitive + matches address too
    res = storage.search(city="MADRID")
    assert len(res) == 1
    res = storage.search(city="calle mayor")
    assert len(res) == 1


def test_search_upcoming(storage):
    today = date(2026, 10, 2)
    past = Analysis(events=[Event(name="old", start_date="2020-01-01")])
    future = Analysis(events=[Event(name="soon", start_date="2026-12-01")])
    ranged = Analysis(events=[Event(name="fair", start_date="2026-09-01", end_date="2026-10-20")])
    undated = Analysis(events=[Event(name="someday")])
    for vid, a in [("1", past), ("2", future), ("3", ranged), ("4", undated)]:
        save(storage, vid, a)
    res = storage.search(upcoming_only=True, today=today)
    names = {e["name"] for r in res for e in r["events"]}
    assert names == {"soon", "fair", "someday"}  # past excluded, unknown-date included
    undated_rows = [r for r in res if r["has_undated_event"]]
    assert len(undated_rows) == 1


def test_migration_normalizes_empty_event_dates(tmp_path):
    from reelmind.storage import SCHEMA_VERSION, Storage

    db = tmp_path / "old.db"
    s = Storage(db)  # fresh -> latest schema
    pk = save(s, "1", Analysis(events=[Event(name="fair", start_date="2026-12-01")]))
    # simulate legacy rows written by the buggy model version
    s._conn.execute("UPDATE events SET start_date='', end_date='' WHERE video_pk=?", (pk,))
    s._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION - 1}")
    s._conn.commit()
    s.close()

    s2 = Storage(db)  # re-open -> migration cleans up
    row = s2.get(pk)
    assert row["events"][0]["start_date"] is None
    res = s2.search(upcoming_only=True, today=date(2026, 10, 2))
    assert [r["id"] for r in res] == [pk]  # unknown-date event included
    s2.close()


def test_fts_punctuation_no_crash(storage):
    save(storage, "1", Analysis(category="restaurant", title="Best 'sushi' & ramen!!"))
    for kw in (["sushi"], ['"weird"'], ["(broken"], ["sushi' OR 1=1"], ["&&&"]):
        res = storage.search(keywords=kw)
        assert isinstance(res, list)
    assert storage.search(keywords=["sushi"])
    assert storage.search(keywords=["ramen"])


def test_usage_recorded(storage):
    from reelmind.llm import Usage

    storage.record_usage("m1", "analyze", Usage(10, 20))
    storage.record_usage("m1", "analyze", Usage(1, 2))
    counts = storage.counts()
    row = next(r for r in counts["usage"] if r["model"] == "m1")
    assert row["prompt_tokens"] == 11 and row["completion_tokens"] == 22
