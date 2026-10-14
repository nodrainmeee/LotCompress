import pytest

from lotcompress.video.compressor import target_video_kbps, email_video_kbps, SAFETY, MIN_VIDEO_KBPS
from lotcompress.video.ffmpeg_tools import VideoInfo
from lotcompress.presets import VIDEO_PRESETS

MB10 = 10 * 1024 * 1024


def test_formula_with_audio():
    # (10 Mio × 8 × 0,85 − 96 kbit/s × 60 s) / 60 s / 1000
    expected = int((MB10 * 8 * SAFETY - 96_000 * 60) / 60 / 1000)
    assert target_video_kbps(MB10, 60, 96, True) == expected


def test_no_audio_gives_more_video():
    assert target_video_kbps(MB10, 60, 96, False) > target_video_kbps(MB10, 60, 96, True)


def test_capped_at_source_bitrate():
    assert target_video_kbps(MB10, 10, 96, True, source_bitrate=500_000) == 500


def test_minimum_for_very_long_video():
    assert target_video_kbps(MB10, 4 * 3600, 96, True) == MIN_VIDEO_KBPS


def test_fits_under_target():
    for d in (5, 30, 60, 180):
        k = target_video_kbps(MB10, d, 96, True)
        assert (k * 1000 + 96_000) * d / 8 <= MB10


def test_email_wrapper_same_result():
    info = VideoInfo(duration=60, width=1920, height=1080, rotation=0, video_codec="h264", audio_codec="aac",
                     has_audio=True, bitrate=12_000_000, audio_bitrate=192_000, fps=30, size=90_000_000)
    s = VIDEO_PRESETS["Email (< 10 Mo)"]
    assert email_video_kbps(info, s, MB10) == target_video_kbps(MB10, 60, s.audio_bitrate, True, 12_000_000)
