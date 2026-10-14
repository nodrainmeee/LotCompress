"""Détection de l'accélération GPU (NVENC / QuickSync) et réglages de qualité par encodeur."""
import subprocess
import threading
from dataclasses import dataclass
from functools import lru_cache

from .. import config
from .ffmpeg_tools import hidden_subprocess_kwargs

ENCODERS = {
    "nvenc": {"h264": "h264_nvenc", "h265": "hevc_nvenc"},
    "qsv": {"h264": "h264_qsv", "h265": "hevc_qsv"},
    "cpu": {"h264": "libx264", "h265": "libx265"},
}
LABELS = {"nvenc": "NVENC détecté", "qsv": "QuickSync détecté", "cpu": "Processeur (CPU)"}
_lock = threading.Lock()


@dataclass(frozen=True)
class Encoder:
    name: str      # ex. "h264_nvenc"
    family: str    # "nvenc", "qsv" ou "cpu"
    codec: str     # "h264" ou "h265"


def _listed_encoders(ffmpeg: str) -> str:
    try:
        r = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, timeout=20,
                           **hidden_subprocess_kwargs())
        return r.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return ""


def _test_encode(ffmpeg: str, encoder: str) -> bool:
    """Vrai encodage de 0,1 s : la présence dans la liste ne garantit pas un GPU utilisable."""
    cmd = [ffmpeg, "-hide_banner", "-v", "error", "-f", "lavfi", "-i", "color=black:s=256x256:d=0.1",
           "-c:v", encoder, "-pix_fmt", "yuv420p" if "qsv" not in encoder else "nv12", "-f", "null", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=20, **hidden_subprocess_kwargs())
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@lru_cache(maxsize=4)
def _available(ffmpeg: str) -> frozenset:
    """Encodeurs matériels réellement fonctionnels (résultat mis en cache)."""
    listed = _listed_encoders(ffmpeg)
    ok = set()
    for family in ("nvenc", "qsv"):
        for enc in ENCODERS[family].values():
            if f" {enc} " in listed and _test_encode(ffmpeg, enc):
                ok.add(enc)
    return frozenset(ok)


def available_encoders() -> frozenset:
    ff = config.ffmpeg_path()
    if not ff:
        return frozenset()
    with _lock:
        return _available(str(ff))


def detected_family() -> str:
    """« nvenc », « qsv » ou « cpu » (pour l'affichage)."""
    av = available_encoders()
    for fam in ("nvenc", "qsv"):
        if any(e in av for e in ENCODERS[fam].values()):
            return fam
    return "cpu"


def choose_encoder(codec: str, use_gpu: bool) -> Encoder:
    """Choisit le meilleur encodeur pour le codec ; repli sur libx264/libx265."""
    if use_gpu:
        av = available_encoders()
        for fam in ("nvenc", "qsv"):
            name = ENCODERS[fam][codec]
            if name in av:
                return Encoder(name, fam, codec)
    return Encoder(ENCODERS["cpu"][codec], "cpu", codec)


def slider_to_crf(quality: int) -> int:
    """Curseur 1-100 → CRF x264 (100 → 14, 1 → 48)."""
    q = max(1, min(100, quality))
    return round(14 + (100 - q) * 34 / 100)


def quality_args(enc: Encoder, quality: int) -> list[str]:
    """Arguments de qualité constante adaptés à l'encodeur."""
    crf = slider_to_crf(quality)
    if enc.family == "cpu":
        if enc.codec == "h265":  # x265 : CRF un peu plus élevé pour une qualité équivalente
            return ["-preset", "medium", "-crf", str(min(51, crf + 3)), "-x265-params", "log-level=error"]
        return ["-preset", "medium", "-crf", str(crf)]
    if enc.family == "nvenc":
        return ["-preset", "p5", "-rc", "vbr", "-cq", str(crf), "-b:v", "0"]
    return ["-preset", "medium", "-global_quality", str(crf)]  # qsv


def bitrate_args(enc: Encoder, kbps: int) -> list[str]:
    """Arguments de débit cible (préréglage Email)."""
    args = ["-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.3)}k", "-bufsize", f"{kbps * 2}k"]
    if enc.family == "cpu":
        args = ["-preset", "medium"] + args
        if enc.codec == "h265":
            args += ["-x265-params", "log-level=error"]
    elif enc.family == "nvenc":
        args = ["-preset", "p5", "-rc", "vbr"] + args
    return args
