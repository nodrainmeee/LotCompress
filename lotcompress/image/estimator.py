"""Aperçu avant/après et estimation de la taille de sortie (encodage en mémoire)."""
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from ..presets import ImageSettings
from .compressor import load_image, compress_image
import io

PREVIEW_MAX = 1200  # Taille max de l'aperçu affiché


@dataclass
class Estimate:
    original_size: int
    estimated_size: int
    original: Image.Image     # Image d'aperçu (originale)
    compressed: Image.Image   # Image d'aperçu (après compression)
    out_format: str
    dimensions: tuple[int, int]


def estimate(path: Path, settings: ImageSettings) -> Estimate:
    """Encode réellement l'image en mémoire pour donner une taille fiable."""
    img = load_image(path)
    data, fmt = compress_image(img, settings)
    after = Image.open(io.BytesIO(data))
    after.load()
    dims = after.size
    before = img.copy()
    before.thumbnail((PREVIEW_MAX, PREVIEW_MAX))
    after.thumbnail((PREVIEW_MAX, PREVIEW_MAX))
    return Estimate(path.stat().st_size, len(data), before, after, fmt, dims)


def human_size(n: float) -> str:
    for unit in ("o", "Ko", "Mo", "Go"):
        if abs(n) < 1024 or unit == "Go":
            return f"{n:.0f} {unit}" if unit == "o" else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024
    return str(n)
