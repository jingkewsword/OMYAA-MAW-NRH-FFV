"""Burn current editor subtitles using the shared toolbox FFmpeg pipeline."""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

from maw.gui_platform import creationflags, startupinfo
from maw.postprocess_ffmpeg import BurnSubtitleRequest, MediaToolError, run_burn_subtitles


def burn_editor_subtitles(
    source: Path, text: str, subtitle_format: str, output_dir: Path,
    *, ffmpeg_path: Path, ffprobe_path: Path,
) -> Path:
    """Write only inside the caller's private directory; probe the bound source."""
    if subtitle_format not in {"ass", "srt"} or not isinstance(text, str) or not text.strip():
        raise MediaToolError("需要有效的 ASS 或 SRT 字幕")
    if not source.is_file():
        raise MediaToolError("当前工程的源媒体文件不存在")
    try:
        probe = subprocess.run(
            [str(ffprobe_path), "-v", "error", "-show_entries",
             "stream=codec_type:stream_disposition=attached_pic:format=duration",
             "-of", "json", str(source)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
            startupinfo=startupinfo(), creationflags=creationflags(),
        )
        if probe.returncode:
            raise MediaToolError((probe.stderr or "无法读取源媒体信息").strip()[-4000:])
        info = json.loads(probe.stdout)
        streams = info["streams"]
        has_video = any(s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic") for s in streams)
        has_audio = any(s.get("codec_type") == "audio" for s in streams)
        if not has_video and not has_audio:
            raise MediaToolError("源媒体没有可用的视频或音频流")
        duration = None
        if not has_video:
            duration = float(info["format"]["duration"])
            if not math.isfinite(duration) or duration <= 0:
                raise ValueError("invalid duration")
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise MediaToolError(f"无法读取源媒体信息：{error}") from error
    subtitle = output_dir / f"subtitles.{subtitle_format}"
    subtitle.write_text(text, encoding="utf-8", newline="\n")
    result = run_burn_subtitles(
        BurnSubtitleRequest(
            media_path=source, subtitle_path=subtitle, output_path=output_dir / "subtitled.mp4",
            green_screen=not has_video, green_screen_audio=not has_video,
            green_screen_duration=duration,
        ), ffmpeg_path=ffmpeg_path,
    )
    return result.media_path
