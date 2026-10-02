import shutil
import subprocess
from pathlib import Path

import pytest

from reelmind.pipeline.media import (
    extract_audio,
    extract_frames,
    ffprobe_duration,
    frame_count,
)

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not installed",
)


@pytest.fixture()
def test_video(tmp_path: Path) -> Path:
    out = tmp_path / "vid.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=3:size=320x240:rate=10",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=3",
            "-shortest",
            str(out),
        ],
        check=True,
    )
    return out


def test_duration(test_video):
    d = ffprobe_duration(test_video)
    assert d is not None and 2.5 < d < 3.5


def test_audio(test_video, tmp_path):
    wav = extract_audio(test_video, tmp_path / "a.wav")
    assert wav is not None and wav.exists()
    assert wav.stat().st_size > 1000


def test_frames_count(test_video, tmp_path):
    frames = extract_frames(test_video, tmp_path / "frames", count=4, max_width=160)
    assert len(frames) == 4
    for f in frames:
        assert f.suffix == ".jpg" and f.stat().st_size > 0


def test_no_audio_video(tmp_path):
    # video with no audio stream -> extract_audio returns None
    out = tmp_path / "silent.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=1:size=64x64:rate=5",
            str(out),
        ],
        check=True,
    )
    assert extract_audio(out, tmp_path / "a.wav") is None
    assert extract_frames(out, tmp_path / "fr", count=2)


def test_frame_count_scaling():
    assert frame_count(None, 4, 8, 20.0) == 4
    assert frame_count(0, 4, 8, 20.0) == 4
    assert frame_count(30, 4, 8, 20.0) == 4
    assert frame_count(60, 4, 8, 20.0) == 4
    assert frame_count(180, 4, 8, 20.0) == 8  # 9 -> capped
    assert frame_count(600, 4, 8, 20.0) == 8


def test_frames_scale_with_duration(tmp_path):
    # 3s test video: still under base count, but proves the kwargs path works
    out = tmp_path / "v.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=45:size=64x64:rate=10",
            "-t",
            "45",
            str(out),
        ],
        check=True,
    )
    frames = extract_frames(out, tmp_path / "sc", count=2, max_count=5, seconds_per_frame=15.0)
    assert len(frames) == 3  # ceil(45/15)=3, within [2,5]


def test_still_image(tmp_path):
    img = tmp_path / "img.jpg"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=0.1:size=64x64:rate=1",
            "-frames:v",
            "1",
            str(img),
        ],
        check=True,
    )
    frames = extract_frames(img, tmp_path / "fr2", count=4)
    assert len(frames) >= 1
