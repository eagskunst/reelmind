"""yt-dlp backed platform base. Concrete platforms provide matches()/parse()."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse, urlunparse

from reelmind.models import FetchedVideo, VideoRef
from reelmind.platforms.base import Platform

if TYPE_CHECKING:
    from reelmind.config import Config

# Prefer small files: <=480p pre-merged, then any pre-merged, then best video+audio, then anything.
FORMAT = "b[height<=480]/b/bv*+ba/best"


def strip_query(url: str) -> str:
    parts = urlparse(url)
    return urlunparse(parts._replace(query="", fragment=""))


def _ydl_opts(cfg: Config, platform_name: str, workdir: Path | None) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    if workdir is not None:
        opts["outtmpl"] = str(workdir / "media.%(ext)s")
        opts["format"] = FORMAT
        opts["merge_output_format"] = "mp4"
    pc = cfg.platform_config(platform_name)
    if pc.cookies_from_browser:
        opts["cookiesfrombrowser"] = (pc.cookies_from_browser,)
    if pc.cookies_file:
        opts["cookiefile"] = pc.cookies_file
    return opts


class YtDlpPlatform(Platform):
    """Download + metadata via the yt_dlp Python API."""

    def _ref_from_info(self, info: dict[str, Any], fallback: VideoRef) -> VideoRef:
        return VideoRef(
            platform=self.name,
            video_id=str(info.get("id") or fallback.video_id),
            url=info.get("webpage_url") or fallback.url,
        )

    def download(self, ref: VideoRef, workdir: Path, cfg: Config) -> FetchedVideo:
        import yt_dlp

        workdir.mkdir(parents=True, exist_ok=True)
        try:
            with yt_dlp.YoutubeDL(_ydl_opts(cfg, self.name, workdir)) as ydl:
                info = ydl.extract_info(ref.url, download=True)
                if info is None:
                    raise RuntimeError(f"yt-dlp returned no info for {ref.url}")
                entry = self._pick_entry(ydl, info, workdir)
                media_path = self._find_media(ydl, entry or info, workdir)
        except Exception as e:
            raise self._with_hint(e, cfg) from e
        return self._to_fetched(info, media_path, ref, entry)

    def _with_hint(self, error: Exception, cfg: Config) -> Exception:
        """Attach a cookies hint to login/auth download failures for any platform."""
        msg = str(error)
        loginish = any(
            s in msg.lower()
            for s in ("login", "cookie", "log in", "private", "sign in", "rate-limit", "403")
        )
        if not loginish:
            return error
        pc = cfg.platform_config(self.name)
        has_cookies = bool(pc.cookies_from_browser or pc.cookies_file)
        hint = (
            f"{self.name} may require login cookies (already configured — "
            "check they are still valid)"
            if has_cookies
            else (
                f"{self.name} may require cookies: set [platforms.{self.name}] "
                "cookies_from_browser or cookies_file"
            )
        )
        return RuntimeError(f"{hint}. Original error: {msg}")

    def _pick_entry(self, ydl: Any, info: dict[str, Any], workdir: Path) -> dict[str, Any] | None:
        """For playlist/carousel results (e.g. Instagram carousels, TikTok photos),
        return the first entry whose downloaded file exists."""
        entries = info.get("entries")
        if not entries:
            return None
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            path = self._entry_filepath(ydl, entry)
            if path is not None and path.exists():
                return entry
        return entries[0] if isinstance(entries[0], dict) else None

    def _entry_filepath(self, ydl: Any, entry: dict[str, Any]) -> Path | None:
        rds = entry.get("requested_downloads") or []
        if rds and rds[0].get("filepath"):
            return Path(rds[0]["filepath"])
        try:
            return Path(ydl.prepare_filename(entry))
        except Exception:
            return None

    def _find_media(self, ydl: Any, info: dict[str, Any], workdir: Path) -> Path | None:
        path = self._entry_filepath(ydl, info) or Path(ydl.prepare_filename(info))
        candidates = [path, *path.parent.glob(f"{path.stem}.*")]
        for cand in candidates:
            if cand.exists() and cand.suffix.lower() not in (".part", ".ytdl"):
                return cand
        files = sorted(
            f for f in workdir.glob("media.*") if f.suffix.lower() not in (".part", ".ytdl")
        )
        return files[0] if files else None

    def _to_fetched(
        self,
        info: dict[str, Any],
        media_path: Path | None,
        ref: VideoRef,
        entry: dict[str, Any] | None = None,
    ) -> FetchedVideo:
        if entry:
            # top-level playlist info wins; entry fills in missing fields
            merged = dict(entry)
            merged.update({k: v for k, v in info.items() if v is not None})
            info = merged
        upload = info.get("upload_date")  # YYYYMMDD
        if upload and re.fullmatch(r"\d{8}", str(upload)):
            upload = f"{upload[:4]}-{upload[4:6]}-{upload[6:8]}"
        description = info.get("description") or ""
        tags = info.get("tags") or []
        if tags:
            description = (description + "\n\n#" + " #".join(tags)).strip()
        raw = json.loads(json.dumps(info, default=str))
        return FetchedVideo(
            ref=self._ref_from_info(info, ref),
            title=info.get("title") or "",
            description=description,
            author=info.get("uploader") or info.get("channel") or info.get("uploader_id") or "",
            upload_date=upload or info.get("release_date"),
            duration=float(info["duration"]) if info.get("duration") is not None else None,
            media_path=media_path,
            raw_meta=raw,
        )

    def expand(self, url: str, cfg: Config) -> list[VideoRef]:
        """Resolve a list/collection/profile URL into video refs via extract_flat."""
        ref = self.parse(url)
        if ref is not None:
            return [ref]
        import yt_dlp

        opts = _ydl_opts(cfg, self.name, None)
        opts["extract_flat"] = True
        refs: list[VideoRef] = []
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info:
            return []
        entries = info.get("entries") or []
        for entry in entries:
            entry_url = entry.get("url") or entry.get("webpage_url") or ""
            if not entry_url:
                continue
            if not entry_url.startswith("http") and entry.get("id"):
                entry_url = self._canonical_url(str(entry["id"]))
            parsed = self.parse(entry_url)
            if parsed:
                refs.append(parsed)
        return refs

    def resolve_short_url(self, url: str, cfg: Config) -> VideoRef | None:
        """Resolve a short/share URL to a canonical VideoRef without downloading media."""
        import yt_dlp

        with yt_dlp.YoutubeDL(_ydl_opts(cfg, self.name, None)) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info:
            return None
        return self._ref_from_info(info, VideoRef(platform=self.name, video_id="", url=url))

    def _canonical_url(self, video_id: str) -> str:
        """Build a canonical URL from an id; subclasses may override."""
        return video_id
