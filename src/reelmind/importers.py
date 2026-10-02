"""Format-agnostic importer: walk text content (json/txt/csv/html/zip), keep supported URLs."""

from __future__ import annotations

import json
import re
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from reelmind.models import VideoRef
from reelmind.platforms.base import PlatformRegistry, default_registry

URL_RE = re.compile(r"https?://[^\s\"'<>\)\]}\\,;]+")

TEXT_SUFFIXES = {".json", ".txt", ".csv", ".html", ".htm", ".md", ".tsv", ".ndjson", ".xml"}


def _iter_json_strings(obj: Any) -> Iterator[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_json_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_json_strings(v)


def _texts_from_bytes(name: str, data: bytes) -> Iterator[str]:
    """Yield all string content from one blob (file body or zip member)."""
    lower = name.lower()
    if lower.endswith(".json"):
        try:
            yield from _iter_json_strings(json.loads(data.decode("utf-8", "replace")))
            return
        except json.JSONDecodeError:
            pass  # fall through to raw-text extraction
    try:
        yield data.decode("utf-8", "replace")
    except Exception:
        return


def _iter_blobs(path: Path) -> Iterator[tuple[str, bytes]]:
    """Yield (name, bytes) for path: files, zip members, or a directory tree."""
    if path.is_dir():
        for child in sorted(path.rglob("*")):
            if child.is_file():
                yield from _iter_blobs(child)
        return
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                if name.endswith("/"):
                    continue
                try:
                    yield name, zf.read(name)
                except Exception:
                    continue
        return
    if path.suffix.lower() in TEXT_SUFFIXES or path.is_file():
        yield path.name, path.read_bytes()


def extract_urls(path: Path) -> list[str]:
    """All http(s) URLs found anywhere under path, in order, deduped."""
    seen: set[str] = set()
    urls: list[str] = []
    for name, data in _iter_blobs(path):
        for text in _texts_from_bytes(name, data):
            for m in URL_RE.finditer(text):
                url = m.group(0).rstrip(".,;!?")
                if url not in seen:
                    seen.add(url)
                    urls.append(url)
    return urls


def import_path(
    path: Path, registry: PlatformRegistry | None = None
) -> tuple[list[VideoRef], list[str]]:
    """Import a saved-list file/export. Returns (refs, unsupported_urls)."""
    registry = registry or default_registry
    refs: list[VideoRef] = []
    unsupported: list[str] = []
    seen: set[tuple[str, str]] = set()
    for url in extract_urls(path):
        platform = registry.for_url(url)
        if platform is None:
            unsupported.append(url)
            continue
        ref = platform.parse(url)
        if ref is None:
            # list/collection URL inside an export — skip; `add` handles those via expand.
            continue
        key = (ref.platform, ref.video_id)
        if key not in seen:
            seen.add(key)
            refs.append(ref)
    return refs, unsupported
