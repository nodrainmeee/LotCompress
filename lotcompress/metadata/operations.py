"""Opérations sur les métadonnées : supprimer, ajouter, corriger.

Règle absolue : aucune fonction ne crée, n'invente ni ne remplace la marque, le modèle
ou l'objectif d'un appareil. Ces balises peuvent seulement être SUPPRIMÉES
(voir exiftool.BLOCKED_TAGS et exiftool.check_args).
"""
import os
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field, asdict, fields
from pathlib import Path
from typing import Callable, Optional

from .. import config
from ..core import output
from ..core.errors import LotCompressError, CancelledError, describe
from ..core.models import Task, Result, Status
from ..video.ffmpeg_tools import require_ffmpeg, hidden_subprocess_kwargs
from . import exiftool
from .exiftool import BlockedTagError, check_args, tag_base, BLOCKED_TAGS

# ---------------------------------------------------------------- Suppressions
REMOVE_GPS = ["-gps:all=", "-XMP:GPS*=", "-XMP-iptcExt:LocationCreated*=", "-Keys:GPSCoordinates=",
              "-UserData:GPSCoordinates=", "-ItemList:GPSCoordinates=", "-Keys:LocationISO6709=",
              "-UserData:LocationInformation="]
REMOVE_CAMERA = ["-Make=", "-Model=", "-LensModel=", "-LensMake=", "-Lens=", "-LensInfo=",
                 "-LensSerialNumber=", "-SerialNumber=", "-BodySerialNumber=", "-InternalSerialNumber=",
                 "-OwnerName=", "-CameraOwnerName=", "-UniqueCameraModel=", "-MakerNotes:all=",
                 "-XMP:Make=", "-XMP:Model=", "-XMP:Lens*=", "-XMP:SerialNumber=",
                 "-Keys:Make=", "-Keys:Model=", "-UserData:Make=", "-UserData:Model=",
                 "-Keys:AndroidManufacturer=", "-Keys:AndroidModel="]
REMOVE_SOFTWARE = ["-Software=", "-ProcessingSoftware=", "-XMP:CreatorTool=",
                   "-XMP-xmpMM:HistorySoftwareAgent=", "-ItemList:Encoder=", "-Keys:Encoder=",
                   "-UserData:Encoder=", "-UserData:Software=", "-UserData:SoftwareVersion=", "-Keys:Software="]
REMOVE_COMMENTS = ["-Comment=", "-UserComment=", "-XPComment=", "-ItemList:Comment=",
                   "-UserData:Comment=", "-Keys:Comment=", "-XMP-exif:UserComment="]
REMOVE_DESCRIPTION = ["-ImageDescription=", "-XMP-dc:Description=", "-IPTC:Caption-Abstract=",
                      "-ItemList:Description=", "-Keys:Description="]

# ISO 639-2 proposées dans l'interface
LANGUAGES = {"fra": "Français", "eng": "Anglais", "spa": "Espagnol", "por": "Portugais",
             "deu": "Allemand", "ita": "Italien", "ara": "Arabe", "zho": "Chinois",
             "jpn": "Japonais", "rus": "Russe", "nld": "Néerlandais", "wol": "Wolof",
             "yor": "Yoruba", "fon": "Fon", "hau": "Haoussa", "swa": "Swahili", "und": "Indéterminée"}
# Orientation EXIF (images) : 1 normal, 3 = 180°, 6 = 90° horaire, 8 = 270° horaire
IMAGE_ORIENTATIONS = {1: "Normale", 3: "Rotation 180°", 6: "Rotation 90° (horaire)",
                      8: "Rotation 270° (horaire)", 2: "Miroir horizontal", 4: "Miroir vertical"}
VIDEO_ROTATION_FROM_ORIENTATION = {1: 0, 3: 180, 6: 90, 8: 270}


@dataclass
class MetaOps:
    """Ensemble d'opérations à appliquer (sérialisable en profil JSON)."""
    remove_gps: bool = False
    remove_camera: bool = False
    remove_software: bool = False
    remove_comments: bool = False
    remove_description: bool = False
    title: str = ""
    description: str = ""
    author: str = ""
    copyright: str = ""
    keywords: list[str] = field(default_factory=list)
    date: str = ""              # « AAAA:MM:JJ HH:MM:SS », vide = inchangée
    orientation: int = 0        # 0 = inchangée, sinon code EXIF 1/3/6/8
    audio_language: str = ""    # code ISO 639-2, vide = inchangée
    custom_tags: dict = field(default_factory=dict)  # Avancé : {"XMP-dc:Rights": "..."} (bloqués refusés)
    overwrite: bool = False
    output_dir: Optional[str] = None  # Dossier de sortie personnalisé (non enregistré dans les profils)
    _is_meta = True  # marqueur pour la file d'attente (attribut de classe, non sérialisé)

    def is_empty(self) -> bool:
        d = asdict(self); d.pop("overwrite"); d.pop("output_dir")
        return not any(d.values())

    def validate(self) -> None:
        if self.date:
            import re
            if not re.fullmatch(r"\d{4}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}", self.date):
                raise LotCompressError("Date invalide (format attendu AAAA:MM:JJ HH:MM:SS)")
        if self.orientation not in (0, *IMAGE_ORIENTATIONS):
            raise LotCompressError("Orientation invalide")
        if self.audio_language and (len(self.audio_language) != 3 or not self.audio_language.isalpha()):
            raise LotCompressError("Langue invalide (code ISO 639-2 à 3 lettres)")
        for k, v in self.custom_tags.items():
            if tag_base(k) in BLOCKED_TAGS or any(b in tag_base(k) for b in ("make", "model", "lens")):
                raise BlockedTagError(f"Balise interdite : « {k} » (marque, modèle ou objectif d'appareil)")
            if not isinstance(v, str) or any(c in k for c in "=<>\n "):
                raise LotCompressError(f"Balise personnalisée invalide : {k}")


def is_video(path: Path) -> bool:
    return path.suffix.lower() in config.VIDEO_EXTENSIONS


def _one_line(text: str) -> str:
    """Remplace tout saut de ligne / caractère de contrôle par une espace."""
    return " ".join("".join(c if c.isprintable() else " " for c in text).split())


def _sanitized(ops: MetaOps) -> MetaOps:
    from dataclasses import replace
    return replace(
        ops,
        title=_one_line(ops.title),
        description=_one_line(ops.description),
        author=_one_line(ops.author),
        copyright=_one_line(ops.copyright),
        keywords=[_one_line(k) for k in ops.keywords if _one_line(k)],
        custom_tags={k: (_one_line(v) if isinstance(v, str) else v) for k, v in ops.custom_tags.items()},
    )


def build_args(ops: MetaOps, video: bool) -> list[str]:
    """Traduit les opérations en arguments ExifTool (une option par élément)."""
    ops = _sanitized(ops)
    ops.validate()
    a: list[str] = []
    if ops.remove_gps: a += REMOVE_GPS
    if ops.remove_camera: a += REMOVE_CAMERA
    if ops.remove_software: a += REMOVE_SOFTWARE
    if ops.remove_comments: a += REMOVE_COMMENTS
    if ops.remove_description: a += REMOVE_DESCRIPTION

    def put(img_tags, vid_tags, value):
        for t in (vid_tags if video else img_tags):
            a.append(f"-{t}={value}")

    if ops.title:
        put(["XMP-dc:Title", "IPTC:ObjectName", "EXIF:XPTitle"], ["ItemList:Title", "Keys:Title", "XMP-dc:Title"], ops.title)
    if ops.description:
        put(["EXIF:ImageDescription", "XMP-dc:Description", "IPTC:Caption-Abstract"],
            ["ItemList:Description", "Keys:Description", "XMP-dc:Description"], ops.description)
    if ops.author:
        put(["EXIF:Artist", "XMP-dc:Creator", "IPTC:By-line"], ["ItemList:Artist", "Keys:Author", "XMP-dc:Creator"], ops.author)
    if ops.copyright:
        put(["EXIF:Copyright", "XMP-dc:Rights", "IPTC:CopyrightNotice"],
            ["ItemList:Copyright", "Keys:Copyright", "XMP-dc:Rights"], ops.copyright)
    if ops.keywords:
        kws = [k.strip() for k in ops.keywords if k.strip()]
        if video:
            a.append(f"-Keys:Keywords={', '.join(kws)}")
            lists = ["XMP-dc:Subject"]
        else:
            lists = ["IPTC:Keywords", "XMP-dc:Subject"]
        for g in lists:  # « -X= » vide la liste existante, puis « -X+= » ajoute chaque mot-clé
            a.append(f"-{g}=")
            a += [f"-{g}+={k}" for k in kws]
    if ops.date:
        if video:
            a += ["-api", "QuickTimeUTC"] + [f"-QuickTime:{t}={ops.date}" for t in
                                             ("CreateDate", "ModifyDate", "MediaCreateDate", "MediaModifyDate",
                                              "TrackCreateDate", "TrackModifyDate")]
        else:
            a += [f"-AllDates={ops.date}"]
    if ops.orientation:
        if video:
            a.append(f"-Rotation={VIDEO_ROTATION_FROM_ORIENTATION.get(ops.orientation, 0)}")
        else:
            a.append(f"-EXIF:Orientation#={ops.orientation}")  # « # » : valeur numérique
    for k, v in ops.custom_tags.items():
        a.append(f"-{k}={v}")
    check_args(a)  # Double vérification anti-faux appareil
    return a


def set_audio_language(path: Path, lang: str, cancel: Optional[threading.Event] = None) -> None:
    """Langue de la piste audio : ExifTool ne sait pas l'écrire, on remuxe sans réencodage (ffmpeg -c copy)."""
    tmp = path.with_name(path.stem + ".lang_tmp" + path.suffix)
    cmd = [str(require_ffmpeg()), "-hide_banner", "-v", "error", "-y", "-i", str(path), "-map", "0",
           "-c", "copy", "-map_metadata", "0", "-movflags", "use_metadata_tags",
           "-metadata:s:a:0", f"language={lang}", str(tmp)]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=3600, **hidden_subprocess_kwargs())
        if r.returncode != 0:
            raise LotCompressError("Langue audio : " + r.stderr.decode("utf-8", "replace").strip()[-200:])
        if cancel and cancel.is_set():
            raise CancelledError("Annulé")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def apply_to_file(path: Path, ops: MetaOps, cancel: Optional[threading.Event] = None) -> None:
    """Applique les opérations EN PLACE (à n'appeler que sur une copie temporaire)."""
    video = is_video(path)
    if video and ops.audio_language:
        set_audio_language(path, ops.audio_language, cancel)
    args = build_args(ops, video)
    if args:
        exiftool.write(path, args)


def process_metadata_task(task: Task, ops: MetaOps, cancel: threading.Event,
                          on_progress: Callable[[int], None] = lambda p: None) -> Result:
    """Copie le fichier (Compressés ou remplacement atomique), applique les opérations. Ne lève jamais."""
    src = task.source
    orig_size = 0
    tmp: Optional[Path] = None
    try:
        orig_size = src.stat().st_size
        if cancel.is_set():
            raise CancelledError("Annulé")
        dest = output.output_path(src, task.root, "", ops.overwrite, ops.output_dir)
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".lc_", suffix=src.suffix, dir=dest.parent)
        os.close(fd); tmp = Path(name)
        shutil.copy2(src, tmp)
        on_progress(30)
        apply_to_file(tmp, ops, cancel)
        if cancel.is_set():
            raise CancelledError("Annulé")
        on_progress(90)
        os.replace(tmp, dest); tmp = None
        on_progress(100)
        return Result(task.id, Status.DONE, orig_size, dest.stat().st_size, dest, "Métadonnées appliquées")
    except CancelledError:
        return Result(task.id, Status.CANCELLED, orig_size, message="Annulé")
    except Exception as e:
        return Result(task.id, Status.ERROR, orig_size, message=describe(e))
    finally:
        if tmp is not None and tmp.exists():
            tmp.unlink()


def preview(path: Path, ops: MetaOps) -> tuple[dict, dict]:
    """Aperçu fidèle : applique sur une copie temporaire et relit (avant, après)."""
    before = exiftool.read(path)
    if path.stat().st_size > 500 * 1024 * 1024:
        raise LotCompressError("Fichier trop volumineux pour l'aperçu (> 500 Mo)")
    with tempfile.TemporaryDirectory(prefix="lc_meta_") as d:
        tmp = Path(d) / ("apercu" + path.suffix)
        shutil.copy2(path, tmp)
        apply_to_file(tmp, ops)
        after = exiftool.read(tmp)
    # Champs propres au fichier (nom, dates système) : sans intérêt pour la comparaison
    for dct in (before, after):
        for k in list(dct):
            if k.startswith(("System:", "ExifTool:")) or k in ("File:FileName",):
                dct.pop(k)
    return before, after
