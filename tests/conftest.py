"""Configuration commune : Qt hors écran, dossiers temporaires isolés."""
import os
import sys
from pathlib import Path

import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Réglages QSettings / données isolés pour toute la session de tests
_SESSION_TMP = tempfile.mkdtemp(prefix="lc_pytest_")
os.environ["XDG_CONFIG_HOME"] = os.path.join(_SESSION_TMP, "config")
os.environ["XDG_DATA_HOME"] = os.path.join(_SESSION_TMP, "data")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest


@pytest.fixture(autouse=True)
def _isolated_dirs(tmp_path, monkeypatch):
    """Profils et journaux dans des dossiers temporaires (jamais ceux de l'utilisateur)."""
    monkeypatch.setenv("LOTCOMPRESS_PROFILES_DIR", str(tmp_path / "profils"))
    monkeypatch.setenv("LOTCOMPRESS_LOG_DIR", str(tmp_path / "logs"))


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])
