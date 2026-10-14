"""Profils de métadonnées enregistrés en JSON dans le dossier de configuration utilisateur."""
import json
import os
import re
from dataclasses import asdict, fields
from pathlib import Path
from typing import Optional

from ..core.errors import LotCompressError
from .operations import MetaOps

SCHEMA_VERSION = 1
_TYPES = {"remove_gps": bool, "remove_camera": bool, "remove_software": bool, "remove_comments": bool,
          "remove_description": bool, "title": str, "description": str, "author": str, "copyright": str,
          "keywords": list, "date": str, "orientation": int, "audio_language": str, "custom_tags": dict}


class ProfileError(LotCompressError):
    pass


def profiles_dir(base: Optional[Path] = None) -> Path:
    """Dossier des profils : QStandardPaths.AppDataLocation/profils (ou LOTCOMPRESS_PROFILES_DIR)."""
    if base is None:
        env = os.environ.get("LOTCOMPRESS_PROFILES_DIR")
        if env:
            base = Path(env)
        else:
            from PySide6.QtCore import QStandardPaths
            base = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)) / "profils"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _file(name: str, base=None) -> Path:
    slug = re.sub(r"[^\w\- ]", "_", name, flags=re.UNICODE).strip() or "profil"
    return profiles_dir(base) / f"{slug}.json"


def to_dict(ops: MetaOps) -> dict:
    d = asdict(ops); d.pop("overwrite", None); d.pop("output_dir", None)
    return d


def from_dict(data: dict) -> MetaOps:
    """Valide le schéma et refuse les balises interdites (marque/modèle/objectif)."""
    if not isinstance(data, dict):
        raise ProfileError("Profil invalide")
    ops_d = data.get("operations", data)
    unknown = set(ops_d) - set(_TYPES)
    if unknown:
        raise ProfileError(f"Champ(s) inconnu(s) dans le profil : {', '.join(sorted(unknown))}")
    for k, v in ops_d.items():
        t = _TYPES[k]
        if not isinstance(v, t) or (t is int and isinstance(v, bool)):
            raise ProfileError(f"Valeur invalide pour « {k} »")
    if not all(isinstance(k, str) for k in ops_d.get("keywords", [])):
        raise ProfileError("Mots-clés invalides")
    ops = MetaOps(**ops_d)
    ops.validate()  # lève BlockedTagError pour Make/Model/Lens…
    return ops


def list_profiles(base=None) -> list[str]:
    names = []
    for f in sorted(profiles_dir(base).glob("*.json")):
        try:
            names.append(json.loads(f.read_text(encoding="utf-8")).get("name", f.stem))
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(names, key=str.lower)


def save_profile(name: str, ops: MetaOps, base=None) -> Path:
    name = name.strip()
    if not name:
        raise ProfileError("Nom de profil vide")
    ops.validate()
    f = _file(name, base)
    f.write_text(json.dumps({"name": name, "version": SCHEMA_VERSION, "operations": to_dict(ops)},
                            ensure_ascii=False, indent=2), encoding="utf-8")
    return f


def load_profile(name: str, base=None) -> MetaOps:
    f = _file(name, base)
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ProfileError(f"Profil introuvable : {name}")
    except (OSError, json.JSONDecodeError) as e:
        raise ProfileError(f"Profil illisible : {e}")
    return from_dict(data)


def rename_profile(old: str, new: str, base=None) -> None:
    ops = load_profile(old, base)
    save_profile(new, ops, base)
    if _file(old, base) != _file(new, base):
        delete_profile(old, base)


def delete_profile(name: str, base=None) -> None:
    f = _file(name, base)
    if f.exists():
        f.unlink()
