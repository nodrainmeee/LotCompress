"""Calcul des chemins de sortie et écriture sûre."""
import os
import tempfile
from pathlib import Path

from .. import config

EXT_FOR_FORMAT = {"JPEG": ".jpg", "WEBP": ".webp", "PNG": ".png", "BMP": ".bmp",
                  "TIFF": ".tif", "HEIF": ".heic", "MP4": ".mp4"}


def output_path(source: Path, root: Path, fmt: str, overwrite: bool,
                out_dir: "str | Path | None" = None) -> Path:
    """Chemin de sortie : « Compressés » à côté de la racine déposée, arborescence conservée.

    out_dir : dossier de sortie personnalisé (arborescence conservée dedans) ; None = « Compressés ».
    En mode écrasement, on remplace l'original (même nom ; extension changée si conversion).
    """
    ext = EXT_FOR_FORMAT.get(fmt, source.suffix.lower())
    if overwrite:
        return source.with_suffix(ext) if ext != source.suffix.lower() else source
    try:
        rel = source.relative_to(root)
    except ValueError:
        rel = Path(source.name)
    base = Path(out_dir) if out_dir else root / config.OUTPUT_DIR_NAME
    target = base / rel.with_suffix(ext)
    return unique_path(target)


def unique_path(path: Path) -> Path:
    """Ajoute « (2) », « (3) »… si le fichier existe déjà."""
    if not path.exists():
        return path
    n = 2
    while True:
        cand = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not cand.exists():
            return cand
        n += 1


def atomic_write(path: Path, data: bytes) -> None:
    """Écrit dans un fichier temporaire du même dossier puis remplace atomiquement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".lc_", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
