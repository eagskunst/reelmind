"""ffmpeg/ffprobe helpers: duration, 16kHz mono wav, evenly spaced JPEG frames."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def has_media_tools() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def ffprobe_duration(media_path: Path) -> float | None:
    """Duration in seconds, or None if it can't be determined (e.g. an image)."""
    proc = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(media_path),
        ]
    )
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    dur = data.get("format", {}).get("duration")
    if dur is not None:
        try:
            return float(dur)
        except ValueError:
            pass
    for stream in data.get("streams", []):
        if stream.get("duration"):
            try:
                return float(stream["duration"])
            except ValueError:
                continue
    return None


def _stream_types(media_path: Path) -> set[str]:
    proc = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            str(media_path),
        ]
    )
    try:
        data = json.loads(proc.stdout)
        return {s.get("codec_type", "") for s in data.get("streams", [])}
    except json.JSONDecodeError:
        return set()


def extract_audio(media_path: Path, out_path: Path) -> Path | None:
    """16kHz mono wav for whisper. Returns None when there is no audio stream."""
    if "audio" not in _stream_types(media_path):
        return None
    proc = _run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(media_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(out_path),
        ]
    )
    return out_path if proc.returncode == 0 and out_path.exists() else None


def extract_frames(
    media_path: Path, out_dir: Path, count: int = 4, max_width: int = 512
) -> list[Path]:
    """`count` frames evenly spaced over the video, skipping the first/last 5%.

    For still images (photo carousels) produces a single frame from whatever exists.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    if "video" not in _stream_types(media_path):
        return []
    duration = ffprobe_duration(media_path)
    if duration is None or duration <= 0 or duration < 1.0:
        # still image / unknown or negligible duration: grab whatever is there
        timestamps = []
    elif count <= 1:
        timestamps = [duration / 2]
    else:
        start, end = duration * 0.05, duration * 0.95
        step = (end - start) / (count - 1)
        timestamps = [start + i * step for i in range(count)]
    scale = f"scale='min(iw,{max_width})':-2"
    frames: list[Path] = []
    for i, ts in enumerate(timestamps or [-1.0]):
        out = out_dir / f"frame_{i:02d}.jpg"
        seek = ["-ss", f"{ts:.3f}"] if ts >= 0 else []
        proc = _run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                *seek,
                "-i",
                str(media_path),
                "-frames:v",
                "1",
                "-vf",
                scale,
                "-q:v",
                "4",
                str(out),
            ]
        )
        if proc.returncode == 0 and out.exists():
            frames.append(out)
    return frames
