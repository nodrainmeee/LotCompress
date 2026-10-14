"""Préréglages de compression."""
from dataclasses import dataclass, replace
from typing import Optional


@dataclass(frozen=True)
class ImageSettings:
    """Réglages appliqués à une image."""
    quality: int = 80                    # 1-100
    max_width: Optional[int] = None      # None = pas de limite
    max_height: Optional[int] = None
    out_format: str = "keep"             # "keep", "JPEG" ou "WEBP"
    max_bytes: Optional[int] = None      # Taille cible maximale (préréglage Email)
    overwrite: bool = False              # Écraser les originaux (confirmation requise)
    output_dir: Optional[str] = None     # Dossier de sortie personnalisé (None = « Compressés »)

    def with_(self, **kw) -> "ImageSettings":
        return replace(self, **kw)


PRESETS: dict[str, ImageSettings] = {
    "Web": ImageSettings(quality=80, max_width=1920, max_height=1920, out_format="WEBP"),
    "Instagram / TikTok": ImageSettings(quality=85, max_width=1080, max_height=1920, out_format="JPEG"),
    "WhatsApp": ImageSettings(quality=75, max_width=1600, max_height=1600, out_format="JPEG"),
    "Email (< 10 Mo)": ImageSettings(quality=85, out_format="JPEG", max_bytes=10 * 1024 * 1024),
    "Personnalisé": ImageSettings(),
}
DEFAULT_PRESET = "Web"


# ---------------------------------------------------------------- Vidéos
@dataclass(frozen=True)
class VideoSettings:
    """Réglages appliqués à une vidéo."""
    codec: str = "h264"                  # "h264" ou "h265"
    quality: int = 60                    # 1-100 (converti en CRF / CQ / global_quality)
    max_long_side: Optional[int] = 1920  # None = résolution d'origine (jamais d'agrandissement)
    pad_to: Optional[tuple[int, int]] = None   # (1080, 1920) : ajuste et complète en noir
    fps_cap: Optional[int] = None        # ex. 30
    audio_bitrate: int = 128             # kbit/s
    target_bytes: Optional[int] = None   # Email : taille cible
    use_gpu: bool = True                 # Utiliser NVENC/QuickSync si détecté
    overwrite: bool = False
    output_dir: Optional[str] = None

    def with_(self, **kw) -> "VideoSettings":
        return replace(self, **kw)


def crf_to_quality(crf: int) -> int:
    """Convertit un CRF x264 (0-51) en valeur de curseur 1-100 (inverse de video.gpu)."""
    return max(1, min(100, round(100 - (crf - 14) * 100 / 34)))


VIDEO_PRESETS: dict[str, VideoSettings] = {
    "Web": VideoSettings(quality=crf_to_quality(23), max_long_side=1920, audio_bitrate=128),
    "Instagram / TikTok": VideoSettings(quality=crf_to_quality(20), max_long_side=None,
                                        pad_to=(1080, 1920), fps_cap=30, audio_bitrate=128),
    "WhatsApp": VideoSettings(quality=crf_to_quality(26), max_long_side=1280, audio_bitrate=96),
    "Email (< 10 Mo)": VideoSettings(quality=crf_to_quality(26), max_long_side=1280, audio_bitrate=96,
                                     target_bytes=10 * 1024 * 1024),
    "Personnalisé": VideoSettings(),
}
