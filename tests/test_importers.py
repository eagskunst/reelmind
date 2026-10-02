import json
import zipfile
from pathlib import Path

from reelmind.importers import extract_urls, import_path

TIKTOK_EXPORT = {
    "Your Activity": {
        "Favorite Videos": {
            "FavoriteVideoList": [
                {
                    "Date": "2025-01-01 10:00:00",
                    "Link": "https://www.tiktok.com/@a/video/1111111111111111111",
                },
                {"Date": "2025-01-02 10:00:00", "Link": "https://vm.tiktok.com/ZMhAbCdEf/"},
                {
                    "Date": "2025-01-03 10:00:00",
                    "Link": "https://www.tiktok.com/@a/video/1111111111111111111",
                },  # dup
            ]
        }
    }
}

IG_EXPORT = {
    "saved_saved_media": [
        {
            "title": "x",
            "string_map_data": {
                "Saved on": {
                    "href": "https://www.instagram.com/reel/CxYzAbC123/",
                    "timestamp": 1720000000,
                }
            },
        },
        {
            "string_map_data": {
                "Saved on": {"href": "https://www.instagram.com/p/DDDDEEEE999/?hl=en"}
            }
        },
    ]
}


def test_tiktok_export_json(tmp_path: Path):
    f = tmp_path / "tiktok.json"
    f.write_text(json.dumps(TIKTOK_EXPORT))
    refs, unsupported = import_path(f)
    assert len(refs) == 2  # dedupe of the repeated video
    assert {r.platform for r in refs} == {"tiktok"}
    assert unsupported == []


def test_instagram_saved_posts(tmp_path: Path):
    f = tmp_path / "saved_posts.json"
    f.write_text(json.dumps(IG_EXPORT))
    refs, _ = import_path(f)
    ids = {r.video_id for r in refs}
    assert ids == {"CxYzAbC123", "DDDDEEEE999"}


def test_txt_file(tmp_path: Path):
    f = tmp_path / "urls.txt"
    f.write_text(
        "check this https://www.tiktok.com/@a/video/2222222222222222222 lol\n"
        "and https://youtu.be/dQw4w9WgXcQ plus junk https://example.com/x\n"
    )
    refs, unsupported = import_path(f)
    assert len(refs) == 2
    assert "https://example.com/x" in unsupported


def test_zip_with_both(tmp_path: Path):
    z = tmp_path / "export.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("data/user_data_tiktok.json", json.dumps(TIKTOK_EXPORT))
        zf.writestr("nested/dir/saved_posts.json", json.dumps(IG_EXPORT))
        zf.writestr("notes.txt", "https://www.youtube.com/shorts/dQw4w9WgXcQ")
    refs, _ = import_path(z)
    platforms = {r.platform for r in refs}
    assert platforms == {"tiktok", "instagram", "youtube"}
    assert len(refs) == 5


def test_directory_walk(tmp_path: Path):
    (tmp_path / "a.txt").write_text("https://www.tiktok.com/@a/video/3333333333333333333")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.json").write_text(json.dumps(IG_EXPORT))
    refs, _ = import_path(tmp_path)
    assert len(refs) == 3


def test_extract_urls_dedup_and_punct(tmp_path: Path):
    f = tmp_path / "x.txt"
    f.write_text("https://example.com/a, and https://example.com/a. https://example.com/b")
    urls = extract_urls(f)
    assert urls.count("https://example.com/a") == 1


def test_unsupported_ignored(tmp_path: Path):
    f = tmp_path / "x.txt"
    f.write_text("https://vimeo.com/123 https://mastodon.social/@x/1")
    refs, unsupported = import_path(f)
    assert refs == []
    assert len(unsupported) == 2
