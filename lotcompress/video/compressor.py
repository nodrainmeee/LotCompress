"""Compression vidéo via FFmpeg (appelé en sous-processus)."""
import os
import shutil
import subprocess
import tempfile
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable, Optional

from ..core import output
from ..core.errors import LotCompressError, CancelledError, describe
from ..core.models import Task, Result, Status
from ..presets import VideoSettings
from .ffmpeg_tools import VideoInfo, probe, require_ffmpeg, hidden_subprocess_kwargs
from .gpu import Encoder, choose_encoder, quality_args, bitrate_args, slider_to_crf

OUT_EXT = ".mp4"
SAFETY = 0.85          # Marge de sécurité pour le préréglage Email
MAX_RETRIES = 2
MIN_VIDEO_KBPS = 80


def _even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def target_dimensions(info: VideoInfo, s: VideoSettings) -> tuple[int, int]:
    """Dimensions de l'image vidéo (avant éventuel remplissage), sans agrandissement."""
    w, h = info.width, info.height
    f = 1.0
    if s.pad_to:
        f = min(1.0, s.pad_to[0] / w, s.pad_to[1] / h)
    elif s.max_long_side:
        f = min(1.0, s.max_long_side / max(w, h))
    return _even(w * f), _even(h * f)


def output_dimensions(info: VideoInfo, s: VideoSettings) -> tuple[int, int]:
    return s.pad_to if s.pad_to else target_dimensions(info, s)


def video_filter(info: VideoInfo, s: VideoSettings) -> str:
    """Chaîne -vf : redimensionnement (proportions conservées, dimensions paires), remplissage noir."""
    w, h = target_dimensions(info, s)
    f = [f"scale={w}:{h}:flags=lanczos"]
    if s.pad_to:
        pw, ph = s.pad_to
        f.append(f"pad={pw}:{ph}:(ow-iw)/2:(oh-ih)/2:color=black")
    f.append("setsar=1")
    if s.fps_cap and info.fps > s.fps_cap + 0.5:
        f.append(f"fps={s.fps_cap}")
    f.append("format=yuv420p")
    return ",".join(f)


def audio_args(info: VideoInfo, s: VideoSettings, force_reencode: bool = False) -> list[str]:
    if not info.has_audio:
        return ["-an"]
    limit = s.audio_bitrate * 1000 * 1.25
    if (not force_reencode and info.audio_codec == "aac" and info.audio_bitrate
            and info.audio_bitrate <= limit):
        return ["-c:a", "copy"]
    return ["-c:a", "aac", "-b:a", f"{s.audio_bitrate}k"]


def target_video_kbps(target_bytes: int, duration: float, audio_kbps: int, has_audio: bool,
                      source_bitrate: int = 0, safety: float = SAFETY,
                      min_kbps: int = MIN_VIDEO_KBPS) -> int:
    """Fonction pure : débit vidéo (kbit/s) pour tenir sous target_bytes.

    (cible × 8 × marge − budget audio) / durée, plafonné au débit source, minimum min_kbps.
    """
    audio_bits = (audio_kbps * 1000 * duration) if has_audio else 0
    video_bits = target_bytes * 8 * safety - audio_bits
    kbps = int(video_bits / duration / 1000)
    if source_bitrate:  # Jamais au-dessus du débit d'origine
        kbps = min(kbps, int(source_bitrate / 1000))
    return max(min_kbps, kbps)


def email_video_kbps(info: VideoInfo, s: VideoSettings, target: int) -> int:
    """Débit vidéo pour tenir dans la taille cible (voir target_video_kbps)."""
    return target_video_kbps(target, info.duration, s.audio_bitrate, info.has_audio, info.bitrate)


def build_command(src: Path, dst: Path, info: VideoInfo, s: VideoSettings, enc: Encoder,
                  video_kbps: Optional[int] = None) -> list[str]:
    """Construit la commande FFmpeg complète."""
    cmd = [str(require_ffmpeg()), "-hide_banner", "-y", "-v", "error",
           "-i", str(src), "-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "0",
           "-vf", video_filter(info, s), "-c:v", enc.name]
    cmd += bitrate_args(enc, video_kbps) if video_kbps else quality_args(enc, s.quality)
    if enc.family != "qsv":
        cmd += ["-pix_fmt", "yuv420p"]
    if enc.codec == "h265":
        cmd += ["-tag:v", "hvc1"]  # Lecture HEVC sur Apple / navigateurs
    # Débit vidéo réduit (Email) : audio réencodé au débit du préréglage pour respecter le budget
    cmd += audio_args(info, s, force_reencode=bool(video_kbps))
    cmd += ["-movflags", "+faststart", "-f", "mp4", "-progress", "pipe:1", "-nostats", str(dst)]
    return cmd


def estimate_size(info: VideoInfo, s: VideoSettings) -> int:
    """Taille estimée (débit × durée). Approximative en mode qualité constante."""
    if s.target_bytes:
        k = email_video_kbps(info, s, s.target_bytes)
        return int((k * 1000 + (s.audio_bitrate * 1000 if info.has_audio else 0)) * info.duration / 8)
    w, h = target_dimensions(info, s)
    fps = min(info.fps or 30, s.fps_cap or 1000)
    crf = slider_to_crf(s.quality)
    bpp = 0.10 * 2 ** ((23 - crf) / 6)             # bits par pixel (empirique, x264)
    if s.codec == "h265":
        bpp *= 0.65
    vbps = bpp * w * h * fps
    src_v = max(0, info.bitrate - info.audio_bitrate) if info.bitrate else vbps
    vbps = min(vbps, src_v * 1.05) if src_v else vbps
    abps = min(s.audio_bitrate * 1000, info.audio_bitrate or s.audio_bitrate * 1000) if info.has_audio else 0
    return int((vbps + abps) * info.duration / 8)


class _Run:
    """Exécute FFmpeg, lit la progression, gère l'annulation (q → terminate → kill)."""

    def __init__(self, cmd, duration, cancel, on_progress):
        self.cmd, self.duration, self.cancel, self.on_progress = cmd, duration, cancel, on_progress
        self.stderr = deque(maxlen=30)
        self.cancelled = False

    def _watch(self, proc):
        while proc.poll() is None:
            if self.cancel.is_set():
                self.cancelled = True
                try:
                    proc.stdin.write(b"q"); proc.stdin.flush()
                except (OSError, ValueError):
                    pass
                try:
                    proc.wait(3)
                except subprocess.TimeoutExpired:
                    proc.terminate()
                    try:
                        proc.wait(3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                return
            time.sleep(0.15)

    def run(self) -> int:
        proc = subprocess.Popen(self.cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, **hidden_subprocess_kwargs())
        err_t = threading.Thread(target=lambda: [self.stderr.append(l.decode("utf-8", "replace").strip())
                                                 for l in proc.stderr], daemon=True)
        watch_t = threading.Thread(target=self._watch, args=(proc,), daemon=True)
        err_t.start(); watch_t.start()
        for raw in proc.stdout:
            line = raw.decode("ascii", "replace").strip()
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                try:
                    us = int(line.split("=", 1)[1])
                except ValueError:
                    continue
                pct = int(100 * us / 1e6 / self.duration) if self.duration else 0
                self.on_progress(max(0, min(99, pct)))
        rc = proc.wait()
        watch_t.join(10); err_t.join(2)
        return rc


def _encode(task_src, tmp, info, s, enc, kbps, cancel, on_progress, lo, hi) -> None:
    cmd = build_command(task_src, tmp, info, s, enc, kbps)
    run = _Run(cmd, info.duration, cancel, lambda p: on_progress(lo + (hi - lo) * p // 100))
    rc = run.run()
    if run.cancelled or cancel.is_set():
        raise CancelledError("Annulé")
    if rc != 0:
        last = next((l for l in reversed(run.stderr) if l), "erreur inconnue")
        raise LotCompressError(f"Échec FFmpeg ({enc.name}) : {last}")


def process_video_task(task: Task, settings: VideoSettings, cancel: threading.Event,
                       on_progress: Callable[[int], None] = lambda p: None) -> Result:
    """Traite une vidéo de bout en bout. Ne lève jamais : les erreurs sont dans le Result."""
    src = task.source
    orig_size = 0
    tmp: Optional[Path] = None
    try:
        orig_size = src.stat().st_size
        info = probe(src)
        on_progress(1)
        enc = choose_encoder(settings.codec, settings.use_gpu)
        dest = output.output_path(src, task.root, "MP4", settings.overwrite, settings.output_dir)
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".lc_", suffix=OUT_EXT, dir=dest.parent)
        os.close(fd)
        tmp = Path(name)

        kbps = email_video_kbps(info, settings, settings.target_bytes) if settings.target_bytes else None
        try:
            _encode(src, tmp, info, settings, enc, kbps, cancel, on_progress, 1, 99)
        except LotCompressError as e:
            if enc.family == "cpu" or isinstance(e, CancelledError):
                raise
            # Échec GPU : on recommence sur le processeur
            enc = choose_encoder(settings.codec, False)
            _encode(src, tmp, info, settings, enc, kbps, cancel, on_progress, 1, 99)

        retries = 0
        while settings.target_bytes and tmp.stat().st_size > settings.target_bytes and retries < MAX_RETRIES:
            retries += 1
            ratio = settings.target_bytes / tmp.stat().st_size
            kbps = max(MIN_VIDEO_KBPS, int(kbps * ratio * SAFETY))
            _encode(src, tmp, info, settings, enc, kbps, cancel, on_progress, 1, 99)
        if settings.target_bytes and tmp.stat().st_size > settings.target_bytes:
            raise LotCompressError("Impossible de passer sous la taille cible (vidéo trop longue)")

        out_size = tmp.stat().st_size
        if out_size >= orig_size and not settings.target_bytes:
            tmp.unlink(); tmp = None
            if settings.overwrite:
                on_progress(100)
                return Result(task.id, Status.KEPT, orig_size, orig_size, src,
                              "Compression inutile : original conservé tel quel")
            keep = output.output_path(src, task.root, "", False, settings.output_dir)
            shutil.copy2(src, keep)
            on_progress(100)
            return Result(task.id, Status.KEPT, orig_size, orig_size, keep,
                          "Résultat plus lourd : copie de l'original conservée")
        os.replace(tmp, dest); tmp = None
        if settings.overwrite and dest != src:
            src.unlink()
        on_progress(100)
        note = f"{enc.name}" + (f", {retries} nouvel(s) essai(s)" if retries else "")
        return Result(task.id, Status.DONE, orig_size, out_size, dest, note)
    except CancelledError:
        return Result(task.id, Status.CANCELLED, orig_size, message="Annulé")
    except Exception as e:
        return Result(task.id, Status.ERROR, orig_size, message=describe(e))
    finally:
        if tmp is not None:  # Fichier partiel supprimé (annulation, erreur)
            try:
                tmp.unlink()
            except OSError:
                pass
