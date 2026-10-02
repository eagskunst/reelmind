"""TikTok: video, photo posts (skipped gracefully), short links, collections."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from reelmind.models import FetchedVideo, VideoRef
from reelmind.platforms.base import register_platform
from reelmind.platforms.ytdlp import YtDlpPlatform, _ydl_opts, strip_query

if TYPE_CHECKING:
    from reelmind.config import Config

_VIDEO_RE = re.compile(r"^/@[^/]+/video/(\d+)")
_PHOTO_RE = re.compile(r"^/@[^/]+/photo/(\d+)")
# Short/share hosts like vm.tiktok.com/ABC123 or vt.tiktok.com/ABC123
_SHORT_RE = re.compile(r"^/([A-Za-z0-9]+)/?$")


class TikTokPlatform(YtDlpPlatform):
    name = "tiktok"

    def matches(self, url: str) -> bool:
        host = urlparse(url).netloc.lower().split(":")[0]
        return host == "tiktok.com" or host.endswith(".tiktok.com")

    def parse(self, url: str) -> VideoRef | None:
        url = strip_query(url)
        parts = urlparse(url)
        if not self.matches(url):
            return None
        host = parts.netloc.lower()
        path = parts.path
        m = _VIDEO_RE.match(path)
        if m:
            return VideoRef(platform=self.name, video_id=m.group(1), url=url)
        m = _PHOTO_RE.match(path)
        if m:
            # Photo post: keep the id so download() can fetch the images, flagged in id.
            return VideoRef(platform=self.name, video_id=f"photo-{m.group(1)}", url=url)
        if host.startswith(("vm.", "vt.")):
            m = _SHORT_RE.match(path)
            if m:
                return VideoRef(platform=self.name, video_id=f"short-{m.group(1)}", url=url)
        return None  # collection/profile/other list URL -> expand()

    def download(self, ref: VideoRef, workdir: Path, cfg: Config) -> FetchedVideo:
        if ref.video_id.startswith("short-"):
            resolved = self.resolve_short_url(ref.url, cfg)
            if resolved is not None:
                ref = resolved
        if ref.video_id.startswith("photo-"):
            return self._download_photos(ref, workdir, cfg)
        fetched = super().download(ref, workdir, cfg)
        return fetched

    def _download_photos(self, ref: VideoRef, workdir: Path, cfg: Config) -> FetchedVideo:
        """Photo posts download as images; no video stream — handled gracefully downstream."""
        import yt_dlp

        workdir.mkdir(parents=True, exist_ok=True)
        opts = _ydl_opts(cfg, self.name, workdir)
        opts.pop("format", None)  # FORMAT has no meaning for image posts
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(ref.url, download=True)
                if info is None:
                    raise RuntimeError(f"yt-dlp returned no info for {ref.url}")
                entry = self._pick_entry(ydl, info, workdir)
                media = self._find_media(ydl, entry or info, workdir)
        except Exception as e:
            raise self._with_hint(e, cfg) from e
        fetched = self._to_fetched(info, media, ref, entry)
        fetched.ref.video_id = str(info.get("id") or ref.video_id.removeprefix("photo-"))
        return fetched

    def _canonical_url(self, video_id: str) -> str:
        if video_id.isdigit():
            return f"https://www.tiktok.com/@_/video/{video_id}"
        return video_id


register_platform(TikTokPlatform())
