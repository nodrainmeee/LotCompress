"""Parcours des fichiers et dossiers déposés."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .. import config
from .models import Task


@dataclass
class ScanResult:
    tasks: list[Task] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)   # Formats non pris en charge


def kind_of(path: Path) -> "str | None":
    """« image », « video » ou None si le format n'est pas pris en charge."""
    ext = path.suffix.lower()
    if ext in config.IMAGE_EXTENSIONS:
        return "image"
    if ext in config.VIDEO_EXTENSIONS:
        return "video"
    return None


def is_supported(path: Path) -> bool:
    return kind_of(path) is not None


def _in_output_dir(path: Path) -> bool:
    """Ne pas re-traiter les fichiers déjà dans un dossier « Compressés »."""
    return config.OUTPUT_DIR_NAME in path.parts


def scan(paths: Iterable[Path]) -> ScanResult:
    """Transforme une liste de chemins déposés en tâches (récursif)."""
    result = ScanResult()
    seen: set[Path] = set()
    for p in paths:
        p = Path(p)
        if p.is_dir():
            root = p
            files = sorted(f for f in p.rglob("*") if f.is_file() and not _in_output_dir(f.relative_to(p)))
        elif p.is_file():
            root, files = p.parent, [p]
        else:
            continue
        for f in files:
            key = f.resolve()
            if key in seen:
                continue
            seen.add(key)
            if is_supported(f):
                result.tasks.append(Task(source=f, root=root, kind=kind_of(f)))
            else:
                result.skipped.append(f)
    return result
