"""Constantes et chemins de l'application."""
import shutil
import sys
from pathlib import Path

APP_NAME = "LotCompress"
ORG_NAME = "LotCompress"
OUTPUT_DIR_NAME = "Compressés"

# Extensions d'images prises en charge (en minuscules, avec le point)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".bmp", ".tif", ".tiff"}

# Extensions vidéo prises en charge
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".3gp", ".wmv"}

# Nombre max de vidéos encodées en parallèle (GPU : 1, processeur : 2)
VIDEO_WORKERS_GPU = 1
VIDEO_WORKERS_CPU = 2

# Délai (ms) avant recalcul de l'aperçu quand on bouge le curseur
PREVIEW_DEBOUNCE_MS = 350


def _base_dir() -> Path:
    """Dossier de base : sys._MEIPASS dans le .exe PyInstaller, sinon la racine du projet."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


BASE_DIR = _base_dir()
ASSETS_DIR = BASE_DIR / "assets"
THEMES_DIR = ASSETS_DIR / "themes"
ICON_PATH = ASSETS_DIR / "icon.ico"
BIN_DIR = BASE_DIR / "bin"
LICENSES_PATH = BASE_DIR / "LICENCES.txt"
FFMPEG_PATH = BIN_DIR / "ffmpeg.exe"
FFPROBE_PATH = BIN_DIR / "ffprobe.exe"
EXIFTOOL_PATH = BIN_DIR / "exiftool.exe"


def resource_path(relative: str) -> Path:
    """Chemin absolu d'une ressource (assets/…, bin/…), dans le .exe comme en développement."""
    return BASE_DIR / relative


def find_tool(name: str) -> "Path | None":
    """Localise un outil externe (ffmpeg, ffprobe, exiftool).

    Ordre : bin/ du bundle (sys._MEIPASS) ou du projet, puis le PATH système.
    """
    exe = name + (".exe" if sys.platform == "win32" else "")
    for cand in (BIN_DIR / exe, BIN_DIR / (name + ".exe"), BIN_DIR / name):
        if cand.is_file():
            return cand
    found = shutil.which(name)
    return Path(found) if found else None


def ffmpeg_path() -> "Path | None":
    return find_tool("ffmpeg")


def ffprobe_path() -> "Path | None":
    return find_tool("ffprobe")


def exiftool_path() -> "Path | None":
    return find_tool("exiftool")


def log_dir() -> Path:
    """Dossier des journaux : %LOCALAPPDATA%\\LotCompress\\logs (Windows), sinon ~/.local/state/LotCompress/logs.

    La variable LOTCOMPRESS_LOG_DIR permet de le remplacer (tests).
    """
    import os
    if os.environ.get("LOTCOMPRESS_LOG_DIR"):
        return Path(os.environ["LOTCOMPRESS_LOG_DIR"])
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / APP_NAME / "logs"
    state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(state) / APP_NAME / "logs"


def missing_tools() -> list[str]:
    """Outils externes introuvables (affichés au démarrage)."""
    out = []
    for label, fn in (("FFmpeg", ffmpeg_path), ("FFprobe", ffprobe_path), ("ExifTool", exiftool_path)):
        if fn() is None:
            out.append(label)
    return out
