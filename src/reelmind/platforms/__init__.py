"""Built-in platforms. Importing this package registers them all."""

# Import side effect: each module registers itself on import.
from reelmind.platforms import instagram, tiktok, youtube  # noqa: F401,E402
from reelmind.platforms.base import (
    Platform,
    PlatformRegistry,
    all_platforms,
    default_registry,
    get_platform_for_url,
    register_platform,
)

__all__ = [
    "Platform",
    "PlatformRegistry",
    "all_platforms",
    "default_registry",
    "get_platform_for_url",
    "register_platform",
    "tiktok",
    "instagram",
    "youtube",
]
