"""Localisation de FFmpeg/FFprobe et analyse des vidéos."""
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .. import config
from ..core.errors import LotCompressError, CorruptedFileError, FilePermissionError


class FFmpegMissingError(LotCompressError):
    """FFmpeg ou FFprobe introuvable."""


def hidden_subprocess_kwargs() -> dict:
    """Arguments subprocess pour ne jamais ouvrir de fenêtre console sous Windows."""
    if sys.platform != "win32":
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0  # SW_HIDE
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000), "startupinfo": si}


def require_ffmpeg() -> Path:
    p = config.ffmpeg_path()
    if not p:
        raise FFmpegMissingError("FFmpeg introuvable : placez ffmpeg.exe dans le dossier bin/")
    return p


def require_ffprobe() -> Path:
    p = config.ffprobe_path()
    if not p:
        raise FFmpegMissingError("FFprobe introuvable : placez ffprobe.exe dans le dossier bin/")
    return p


@dataclass
class VideoInfo:
    duration: float          # secondes
    width: int               # dimensions affichées (rotation appliquée)
    height: int
    rotation: int            # degrés (0, 90, 180, 270)
    video_codec: str
    audio_codec: str | None
    has_audio: bool
    bitrate: int             # bit/s (global)
    audio_bitrate: int       # bit/s (0 si inconnu)
    fps: float
    size: int                # octets


def _rotation(stream: dict) -> int:
    rot = 0
    for sd in stream.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(float(sd["rotation"]))
    if not rot and "rotate" in (stream.get("tags") or {}):
        rot = int(stream["tags"]["rotate"])
    return abs(rot) % 360


def _fps(rate: str) -> float:
    try:
        n, d = rate.split("/")
        return float(n) / float(d) if float(d) else 0.0
    except (ValueError, AttributeError):
        return 0.0


def probe(path: Path) -> VideoInfo:
    """Analyse un fichier avec ffprobe (sortie JSON)."""
    if not path.exists():
        raise FileNotFoundError(path)
    try:
        with open(path, "rb"):
            pass
    except PermissionError as e:
        raise FilePermissionError("Accès refusé (permissions insuffisantes)") from e
    cmd = [str(require_ffprobe()), "-v", "error", "-print_format", "json",
           "-show_format", "-show_streams", str(path)]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=60, **hidden_subprocess_kwargs())
    except subprocess.TimeoutExpired as e:
        raise CorruptedFileError("Analyse trop longue : fichier probablement corrompu") from e
    try:
        data = json.loads(r.stdout.decode("utf-8", "replace") or "{}")
    except json.JSONDecodeError:
        data = {}
    streams = data.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video"
              and not (s.get("disposition") or {}).get("attached_pic")), None)
    if r.returncode != 0 or v is None:
        err = r.stderr.decode("utf-8", "replace").strip().splitlines()
        raise CorruptedFileError("Vidéo illisible ou corrompue" + (f" : {err[-1]}" if err else ""))
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = data.get("format") or {}
    try:
        duration = float(fmt.get("duration") or v.get("duration") or 0)
    except ValueError:
        duration = 0.0
    if duration <= 0:
        raise CorruptedFileError("Durée inconnue : fichier probablement corrompu")
    w, h, rot = int(v.get("width") or 0), int(v.get("height") or 0), _rotation(v)
    if rot in (90, 270):
        w, h = h, w
    return VideoInfo(duration=duration, width=w, height=h, rotation=rot,
                     video_codec=v.get("codec_name", "?"),
                     audio_codec=a.get("codec_name") if a else None, has_audio=a is not None,
                     bitrate=int(fmt.get("bit_rate") or 0),
                     audio_bitrate=int((a or {}).get("bit_rate") or 0),
                     fps=_fps(v.get("avg_frame_rate") or v.get("r_frame_rate") or "0/1"),
                     size=path.stat().st_size)
