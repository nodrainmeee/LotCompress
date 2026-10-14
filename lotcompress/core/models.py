"""Structures de données de la file d'attente."""
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional
import itertools

_ids = itertools.count(1)


class Status(Enum):
    PENDING = "En attente"
    RUNNING = "En cours"
    DONE = "Terminé"
    KEPT = "Original conservé"
    ERROR = "Erreur"
    CANCELLED = "Annulé"
    SKIPPED = "Ignoré"


@dataclass
class Task:
    """Un fichier à traiter."""
    source: Path
    root: Path                       # Dossier déposé (pour conserver l'arborescence)
    kind: str = "image"              # "image" ou "video"
    id: int = field(default_factory=lambda: next(_ids))
    status: Status = Status.PENDING
    progress: int = 0
    message: str = ""


@dataclass
class Result:
    """Résultat du traitement d'un fichier."""
    task_id: int
    status: Status
    original_size: int = 0
    output_size: int = 0
    output_path: Optional[Path] = None
    message: str = ""

    @property
    def saved(self) -> int:
        if self.status in (Status.DONE, Status.KEPT):
            return max(0, self.original_size - self.output_size)
        return 0
