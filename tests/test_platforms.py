from reelmind.platforms import default_registry


def parse(url: str):
    p = default_registry.for_url(url)
    return p.parse(url) if p else None


class TestTikTok:
    def test_full_video_url(self):
        ref = parse("https://www.tiktok.com/@chef/video/7234567890123456789")
        assert ref is not None
        assert ref.platform == "tiktok"
        assert ref.video_id == "7234567890123456789"

    def test_query_string_stripped(self):
        ref = parse("https://www.tiktok.com/@chef/video/7234567890123456789?is_copy_url=1&lang=en")
        assert ref is not None and ref.video_id == "7234567890123456789"
        assert "?" not in ref.url

    def test_mobile_host(self):
        ref = parse("https://m.tiktok.com/@chef/video/7234567890123456789")
        assert ref is not None and ref.video_id == "7234567890123456789"

    def test_short_link(self):
        for url in ("https://vm.tiktok.com/ZMhAbCdEf/", "https://vt.tiktok.com/ZMhAbCdEf/"):
            ref = parse(url)
            assert ref is not None
            assert ref.platform == "tiktok"
            assert ref.video_id.startswith("short-")

    def test_photo_post_graceful(self):
        ref = parse("https://www.tiktok.com/@chef/photo/7234567890123456789")
        assert ref is not None  # parsed; download handles images gracefully
        assert ref.video_id.startswith("photo-")

    def test_list_url_returns_none(self):
        platform = default_registry.for_url("https://www.tiktok.com/@chef")
        assert platform is not None and platform.parse("https://www.tiktok.com/@chef") is None


class TestInstagram:
    def test_variants(self):
        for kind in ("p", "reel", "reels", "tv"):
            url = f"https://www.instagram.com/{kind}/CxYzAbC123/?utm_source=ig_web"
            ref = parse(url)
            assert ref is not None, url
            assert ref.platform == "instagram"
            assert ref.video_id == "CxYzAbC123"
            assert ref.url == "https://www.instagram.com/p/CxYzAbC123/"

    def test_profile_returns_none(self):
        platform = default_registry.for_url("https://www.instagram.com/someuser/")
        assert platform is not None
        assert platform.parse("https://www.instagram.com/someuser/") is None


class TestYouTube:
    def test_shorts(self):
        ref = parse("https://www.youtube.com/shorts/dQw4w9WgXcQ")
        assert ref is not None and ref.video_id == "dQw4w9WgXcQ"

    def test_watch(self):
        ref = parse("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=3s")
        assert ref is not None and ref.video_id == "dQw4w9WgXcQ"

    def test_youtu_be(self):
        ref = parse("https://youtu.be/dQw4w9WgXcQ?si=xyz")
        assert ref is not None and ref.video_id == "dQw4w9WgXcQ"


def test_unsupported_url_no_platform():
    assert default_registry.for_url("https://example.com/foo") is None
    assert default_registry.for_url("https://vimeo.com/12345") is None
