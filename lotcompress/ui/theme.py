"""Thème clair/sombre, mémorisé avec QSettings."""
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from .. import config

THEMES = ("clair", "sombre")


def load_theme() -> str:
    t = QSettings(config.ORG_NAME, config.APP_NAME).value("theme", "clair")
    return t if t in THEMES else "clair"


def save_theme(name: str) -> None:
    QSettings(config.ORG_NAME, config.APP_NAME).setValue("theme", name)


def apply_theme(app: QApplication, name: str) -> None:
    app.setStyle("Fusion")
    qss = config.THEMES_DIR / f"{name}.qss"
    app.setStyleSheet(qss.read_text(encoding="utf-8") if qss.exists() else "")
    app.setProperty("lc_theme", name)
