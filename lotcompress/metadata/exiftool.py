"""Interface ExifTool : processus persistant (-stay_open) avec repli sur un appel simple."""
import atexit
import json
import queue
import subprocess
import threading
from pathlib import Path
from typing import Optional

from .. import config
from ..core.errors import LotCompressError, CorruptedFileError, FilePermissionError
from ..video.ffmpeg_tools import hidden_subprocess_kwargs

TIMEOUT = 60  # secondes par commande

# Balises d'identification de l'appareil : seule la SUPPRESSION est autorisée.
# Toute écriture (valeur non vide, copie « < », ajout « += ») est refusée.
BLOCKED_TAGS = {
    "make", "model", "lensmodel", "lensmake", "lens", "lensinfo", "lensid", "lensspec",
    "lenstype", "cameramodelname", "uniquecameramodel", "localizedcameramodel",
    "camerabrand", "cameramake", "cameramodel", "androidmanufacturer", "androidmodel",
}


class ExifToolMissingError(LotCompressError):
    pass


class BlockedTagError(LotCompressError):
    pass


def tag_base(name: str) -> str:
    """« -XMP-tiff:Make » → « make » (sans groupe, sans index de copie)."""
    name = name.lstrip("-").split(":")[-1]
    return name.strip().lower()


def check_args(args: list[str]) -> None:
    """Refuse toute écriture d'une balise d'appareil/objectif (sécurité anti-faux appareil)."""
    for a in args:
        if any(c in a for c in ("\n", "\r", "\x00")):
            raise LotCompressError("Caractère interdit (saut de ligne) dans une valeur de métadonnée")
        if not a.startswith("-"):
            continue
        for op in ("+=", "-=", "<", "="):
            if op in a:
                name, value = a.split(op, 1)
                break
        else:
            continue
        base = tag_base(name)
        if base.endswith(("+", "-")):
            base = base[:-1]
        if base in BLOCKED_TAGS or any(b in base for b in ("make", "model", "lens")) and base not in ("makernotes",):
            if not (op == "=" and value == ""):
                raise BlockedTagError(f"Modification interdite de la balise « {name.lstrip('-')} » "
                                      "(seule la suppression est permise)")


def require_exiftool() -> Path:
    p = config.exiftool_path()
    if not p:
        raise ExifToolMissingError("ExifTool introuvable : placez exiftool.exe dans le dossier bin/")
    return p


class _StayOpen:
    """Processus ExifTool unique, piloté par « -@ - » (beaucoup plus rapide qu'un appel par fichier)."""

    def __init__(self, exe: Path):
        self.proc = subprocess.Popen(
            [str(exe), "-stay_open", "True", "-@", "-", "-common_args", "-charset", "filename=utf8"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            **hidden_subprocess_kwargs())
        self.out: "queue.Queue[bytes]" = queue.Queue()
        self.err: "queue.Queue[bytes]" = queue.Queue()
        for pipe, q in ((self.proc.stdout, self.out), (self.proc.stderr, self.err)):
            threading.Thread(target=self._pump, args=(pipe, q), daemon=True).start()
        self.n = 0
        self.lock = threading.Lock()

    @staticmethod
    def _pump(pipe, q):
        for line in pipe:
            q.put(line)
        q.put(b"")  # fin de flux

    def _collect(self, q, marker: bytes) -> str:
        lines = []
        while True:
            line = q.get(timeout=TIMEOUT)
            if line == b"":
                raise LotCompressError("ExifTool s'est arrêté de façon inattendue")
            if line.strip() == marker:
                return b"".join(lines).decode("utf-8", "replace")
            lines.append(line)

    def run(self, args: list[str]) -> tuple[str, str]:
        with self.lock:
            self.n += 1
            m = f"{{ready{self.n}}}"
            payload = "\n".join(args + ["-echo4", m, f"-execute{self.n}"]) + "\n"
            self.proc.stdin.write(payload.encode("utf-8")); self.proc.stdin.flush()
            try:
                out = self._collect(self.out, m.encode())
                err = self._collect(self.err, m.encode())
            except queue.Empty:
                self.close()
                raise LotCompressError("ExifTool ne répond plus (délai dépassé)")
            return out, err

    def alive(self) -> bool:
        return self.proc.poll() is None

    def close(self):
        try:
            self.proc.stdin.write(b"-stay_open\nFalse\n"); self.proc.stdin.flush()
            self.proc.wait(3)
        except Exception:
            self.proc.kill()


_instance: Optional[_StayOpen] = None
_ilock = threading.Lock()


def _run_simple(args: list[str]) -> tuple[str, str]:
    """Repli : un processus ExifTool par commande (arguments passés par fichier UTF-8 via stdin)."""
    try:
        r = subprocess.run([str(require_exiftool()), "-charset", "filename=utf8", "-@", "-"],
                           input="\n".join(args).encode("utf-8"), capture_output=True,
                           timeout=TIMEOUT, **hidden_subprocess_kwargs())
    except subprocess.TimeoutExpired as e:
        raise LotCompressError("ExifTool ne répond plus (délai dépassé)") from e
    return r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


def run(args: list[str]) -> tuple[str, str]:
    """Exécute une commande ExifTool (une option par élément ; pas de guillemets)."""
    global _instance
    exe = require_exiftool()
    with _ilock:
        if _instance is None or not _instance.alive():
            try:
                _instance = _StayOpen(exe)
            except OSError:
                _instance = None
        inst = _instance
    if inst is None:
        return _run_simple(args)
    try:
        return inst.run(args)
    except LotCompressError:
        with _ilock:
            _instance = None
        return _run_simple(args)


@atexit.register
def shutdown():
    global _instance
    if _instance is not None:
        _instance.close(); _instance = None


def _check_file(path: Path):
    if not path.exists():
        raise FileNotFoundError(path)
    try:
        with open(path, "rb"):
            pass
    except PermissionError as e:
        raise FilePermissionError("Accès refusé (permissions insuffisantes)") from e


def read(path: Path) -> dict:
    """Lit toutes les métadonnées (« Groupe:Balise » → valeur)."""
    _check_file(path)
    out, err = run(["-j", "-G1", "-a", "-api", "QuickTimeUTC", str(path)])
    try:
        data = json.loads(out)[0]
    except (json.JSONDecodeError, IndexError):
        raise CorruptedFileError("Métadonnées illisibles : " + (err.strip() or "fichier corrompu"))
    if "Error" in data.get("ExifTool:Error", "") or data.get("ExifTool:Error"):
        raise CorruptedFileError(f"Fichier illisible : {data['ExifTool:Error']}")
    data.pop("SourceFile", None)
    return data


def write(path: Path, args: list[str]) -> None:
    """Écrit sur le fichier (en place : appelé sur une copie temporaire)."""
    check_args(args)
    _check_file(path)
    out, err = run(args + ["-overwrite_original", "-m", str(path)])
    msg = (err or "").strip()
    if "files updated" in out and "0 image files updated" not in out or "unchanged" in out:
        return
    line = next((l for l in msg.splitlines() if "Error" in l), msg or out.strip() or "échec inconnu")
    if "Not a valid" in line or "format" in line.lower() or "corrupt" in line.lower():
        raise CorruptedFileError(f"Format non pris en charge ou fichier corrompu : {line}")
    raise LotCompressError(f"ExifTool : {line}")
