"""Platform abstraction + registry. Adding a platform = one file + @register_platform."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

from reelmind.models import FetchedVideo, VideoRef

if TYPE_CHECKING:
    from reelmind.config import Config


class Platform(ABC):
    """A video source. `parse` returns None for list/collection URLs (handled by `expand`)."""

    name: str = "abstract"

    @abstractmethod
    def matches(self, url: str) -> bool:
        """True if this platform owns the URL (video or list)."""

    @abstractmethod
    def parse(self, url: str) -> VideoRef | None:
        """URL -> VideoRef, or None if it's a list/collection/profile URL."""

    def expand(self, url: str, cfg: Config) -> list[VideoRef]:
        """List/collection/profile URL -> video refs. Default: just parse()."""
        ref = self.parse(url)
        return [ref] if ref else []

    @abstractmethod
    def download(self, ref: VideoRef, workdir: Path, cfg: Config) -> FetchedVideo:
        """Fetch metadata + media for a video into workdir."""


class PlatformRegistry:
    def __init__(self) -> None:
        self._platforms: list[Platform] = []

    def register(self, platform: Platform) -> Platform:
        self._platforms.append(platform)
        return platform

    def for_url(self, url: str) -> Platform | None:
        for p in self._platforms:
            if p.matches(url):
                return p
        return None

    def for_name(self, name: str) -> Platform | None:
        for p in self._platforms:
            if p.name == name:
                return p
        return None

    def all(self) -> list[Platform]:
        return list(self._platforms)


default_registry = PlatformRegistry()


def register_platform(platform: Platform) -> Platform:
    return default_registry.register(platform)


def get_platform_for_url(url: str, registry: PlatformRegistry | None = None) -> Platform | None:
    return (registry or default_registry).for_url(url)


def all_platforms(registry: PlatformRegistry | None = None) -> list[Platform]:
    return (registry or default_registry).all()
