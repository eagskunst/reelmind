"""Instagram: /p/, /reel/, /reels/, /tv/ shortcodes. Cookies usually required — see config."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from reelmind.models import VideoRef
from reelmind.platforms.base import register_platform
from reelmind.platforms.ytdlp import YtDlpPlatform, strip_query

_POST_RE = re.compile(r"^/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)")


class InstagramPlatform(YtDlpPlatform):
    name = "instagram"

    def matches(self, url: str) -> bool:
        host = urlparse(url).netloc.lower().split(":")[0]
        return host == "instagram.com" or host.endswith(".instagram.com")

    def parse(self, url: str) -> VideoRef | None:
        url = strip_query(url)
        if not self.matches(url):
            return None
        m = _POST_RE.match(urlparse(url).path)
        if m:
            return VideoRef(
                platform=self.name,
                video_id=m.group(1),
                url=f"https://www.instagram.com/p/{m.group(1)}/",
            )
        return None

    def _canonical_url(self, video_id: str) -> str:
        return f"https://www.instagram.com/p/{video_id}/"


register_platform(InstagramPlatform())
