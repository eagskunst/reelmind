"""YouTube Shorts + watch + youtu.be — mainly here to demonstrate extensibility."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from reelmind.models import VideoRef
from reelmind.platforms.base import register_platform
from reelmind.platforms.ytdlp import YtDlpPlatform, strip_query

_SHORTS_RE = re.compile(r"^/shorts/([A-Za-z0-9_-]+)")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,}$")


class YouTubePlatform(YtDlpPlatform):
    name = "youtube"

    def matches(self, url: str) -> bool:
        host = urlparse(url).netloc.lower().split(":")[0]
        return host in ("youtu.be",) or host == "youtube.com" or host.endswith(".youtube.com")

    def parse(self, url: str) -> VideoRef | None:
        parts = urlparse(strip_query(url))
        if not self.matches(url):
            return None
        host = parts.netloc.lower()
        video_id: str | None = None
        if host == "youtu.be" or host.endswith(".youtu.be"):
            candidate = parts.path.lstrip("/")
            if _ID_RE.match(candidate):
                video_id = candidate
        else:
            m = _SHORTS_RE.match(parts.path)
            if m:
                video_id = m.group(1)
            elif parts.path == "/watch":
                # need the query string for ?v=
                qs = parse_qs(urlparse(url).query)
                v = qs.get("v", [None])[0]
                if v:
                    video_id = v
        if video_id:
            return VideoRef(
                platform=self.name,
                video_id=video_id,
                url=f"https://www.youtube.com/watch?v={video_id}",
            )
        return None

    def _canonical_url(self, video_id: str) -> str:
        return f"https://www.youtube.com/watch?v={video_id}"


register_platform(YouTubePlatform())
