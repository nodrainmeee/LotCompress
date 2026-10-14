"""Compression d'images avec Pillow (+ pillow-heif pour HEIC/HEIF)."""
import io
import shutil
import threading
from pathlib import Path
from typing import Callable, Optional

from PIL import Image, ImageOps, UnidentifiedImageError

try:  # Lecture HEIC/HEIF
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:  # pragma: no cover - module facultatif
    pillow_heif = None

from ..presets import ImageSettings
from ..core import output
from ..core.errors import (CorruptedFileError, UnsupportedFormatError, FilePermissionError,
                           CancelledError, describe)
from ..core.models import Task, Result, Status

# Formats que l'on peut réécrire tels quels ; les autres (HEIC, BMP, TIFF) passent en JPEG
_KEEPABLE = {"JPEG", "PNG", "WEBP"}
MIN_QUALITY = 20


def load_image(path: Path) -> Image.Image:
    """Ouvre et décode complètement l'image, orientation EXIF appliquée."""
    try:
        img = Image.open(path)
        img.load()
    except PermissionError as e:
        raise FilePermissionError("Accès refusé (permissions insuffisantes)") from e
    except UnidentifiedImageError as e:
        raise UnsupportedFormatError("Format non reconnu ou fichier corrompu") from e
    except (OSError, SyntaxError, ValueError) as e:
        raise CorruptedFileError(f"Fichier corrompu : {e}") from e
    icc = img.info.get("icc_profile")
    src_fmt = img.format
    img = ImageOps.exif_transpose(img)
    img.info["icc_profile"] = icc
    img.info["src_format"] = src_fmt
    return img


def target_format(img: Image.Image, settings: ImageSettings) -> str:
    if settings.out_format in ("JPEG", "WEBP"):
        return settings.out_format
    src = img.info.get("src_format") or "JPEG"
    return src if src in _KEEPABLE else "JPEG"


def _resize(img: Image.Image, max_w: Optional[int], max_h: Optional[int]) -> Image.Image:
    if not max_w and not max_h:
        return img
    w, h = img.size
    mw, mh = max_w or w, max_h or h
    if w <= mw and h <= mh:
        return img
    out = img.copy()
    out.thumbnail((mw, mh), Image.Resampling.LANCZOS)
    out.info = img.info
    return out


def _prepare_mode(img: Image.Image, fmt: str) -> Image.Image:
    """Adapte le mode couleur ; transparence → fond blanc pour le JPEG."""
    info = img.info
    if fmt == "JPEG":
        if img.mode in ("RGBA", "LA", "P", "PA") or (img.mode == "P" and "transparency" in info):
            rgba = img.convert("RGBA")
            bg = Image.new("RGB", rgba.size, (255, 255, 255))
            bg.paste(rgba, mask=rgba.getchannel("A"))
            img = bg
        elif img.mode not in ("RGB", "L", "CMYK"):
            img = img.convert("RGB")
    elif fmt == "WEBP":
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "A" in img.mode or "transparency" in info else "RGB")
    img.info = info
    return img


def encode(img: Image.Image, fmt: str, quality: int) -> bytes:
    """Encode en mémoire et renvoie les octets."""
    buf = io.BytesIO()
    kw: dict = {}
    icc = img.info.get("icc_profile")
    if icc:
        kw["icc_profile"] = icc
    if fmt == "JPEG":
        kw.update(quality=quality, optimize=True, progressive=True)
    elif fmt == "WEBP":
        kw.update(quality=quality, method=4)
    elif fmt == "PNG":
        kw.update(optimize=True)
    img.save(buf, format=fmt, **kw)
    return buf.getvalue()


def compress_image(img: Image.Image, settings: ImageSettings,
                   cancel: Optional[threading.Event] = None) -> tuple[bytes, str]:
    """Applique redimensionnement, conversion et qualité. Renvoie (octets, format)."""
    fmt = target_format(img, settings)
    work = _prepare_mode(_resize(img, settings.max_width, settings.max_height), fmt)
    quality = settings.quality
    data = encode(work, fmt, quality)
    if settings.max_bytes:
        # Email : baisse progressive de la qualité puis de la taille jusqu'à passer sous la cible
        if fmt == "PNG":
            fmt, work = "JPEG", _prepare_mode(work, "JPEG")
            data = encode(work, fmt, quality)
        while len(data) > settings.max_bytes:
            if cancel and cancel.is_set():
                raise CancelledError("Annulé")
            if quality > MIN_QUALITY:
                quality = max(MIN_QUALITY, quality - 10)
            else:
                w, h = work.size
                if max(w, h) < 200:
                    break
                work = work.resize((int(w * 0.85), int(h * 0.85)), Image.Resampling.LANCZOS)
                work.info = img.info
            data = encode(work, fmt, quality)
    return data, fmt


def process_task(task: Task, settings: ImageSettings, cancel: threading.Event,
                 on_progress: Callable[[int], None] = lambda p: None) -> Result:
    """Traite un fichier de bout en bout. Ne lève jamais : toute erreur est dans le Result."""
    src = task.source
    orig_size = 0
    try:
        orig_size = src.stat().st_size
        on_progress(10)
        img = load_image(src)
        if cancel.is_set():
            raise CancelledError("Annulé")
        on_progress(40)
        data, fmt = compress_image(img, settings, cancel)
        if cancel.is_set():
            raise CancelledError("Annulé")
        on_progress(80)
        if len(data) >= orig_size:
            # Le résultat est plus lourd : on garde l'original
            if settings.overwrite:
                on_progress(100)
                return Result(task.id, Status.KEPT, orig_size, orig_size, src,
                              "Compression inutile : original conservé tel quel")
            dest = output.output_path(src, task.root, "", False, settings.output_dir)  # extension d'origine
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            on_progress(100)
            return Result(task.id, Status.KEPT, orig_size, orig_size, dest,
                          "Résultat plus lourd : copie de l'original conservée")
        dest = output.output_path(src, task.root, fmt, settings.overwrite, settings.output_dir)
        output.atomic_write(dest, data)
        if settings.overwrite and dest != src:
            src.unlink()  # Conversion de format en mode écrasement : on retire l'ancien fichier
        on_progress(100)
        return Result(task.id, Status.DONE, orig_size, len(data), dest, "")
    except CancelledError:
        return Result(task.id, Status.CANCELLED, message="Annulé")
    except Exception as e:  # Jamais de plantage : l'erreur est affichée dans la file
        return Result(task.id, Status.ERROR, orig_size, message=describe(e))
