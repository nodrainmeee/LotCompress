"""Journalisation et gestion globale des erreurs : jamais de plantage silencieux.

- Journal tournant : %LOCALAPPDATA%\\LotCompress\\logs\\lotcompress.log (voir config.log_dir)
- sys.excepthook, threading.excepthook et messages Qt redirigés vers le journal
- Message d'erreur clair en français, toujours affiché depuis le thread de l'interface
"""
import logging
import sys
import threading
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from . import config, __version__

log = logging.getLogger("lotcompress")
_notifier = None


def setup_logging() -> Path:
    """Configure le journal tournant (1 Mo × 3) et renvoie son chemin."""
    d = config.log_dir()
    path = d / "lotcompress.log"
    if any(isinstance(h, RotatingFileHandler) for h in log.handlers):
        return path
    log.setLevel(logging.INFO)
    try:
        d.mkdir(parents=True, exist_ok=True)
        h = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(threadName)s] %(message)s"))
        log.addHandler(h)
    except OSError:  # Dossier non inscriptible : on continue sans fichier
        log.addHandler(logging.StreamHandler())
    log.info("LotCompress %s démarré (Python %s, %s)", __version__, sys.version.split()[0], sys.platform)
    return path


def _make_notifier():
    """Objet Qt créé dans le thread GUI : les signaux émis ailleurs y sont exécutés (connexion en file)."""
    from PySide6.QtCore import QObject, Signal, Qt

    class Notifier(QObject):
        error = Signal(str, str)

        def __init__(self):
            super().__init__()
            self._showing = False
            self.error.connect(self._show, Qt.QueuedConnection)

        def _show(self, summary: str, details: str):
            if self._showing:      # Pas de cascade de fenêtres (ré-entrance)
                return
            self._showing = True
            try:
                from PySide6.QtWidgets import QMessageBox
                box = QMessageBox(QMessageBox.Critical, "LotCompress — erreur inattendue",
                                  "Une erreur inattendue s'est produite. Vos fichiers originaux n'ont pas été modifiés.\n\n"
                                  f"{summary}\n\nDétails enregistrés dans :\n{config.log_dir() / 'lotcompress.log'}")
                box.setDetailedText(details)
                box.exec()
            except Exception:
                log.exception("Impossible d'afficher la boîte d'erreur")
            finally:
                self._showing = False

    return Notifier()


def report(exc_type, exc, tb, where: str = "") -> None:
    """Journalise l'exception et demande l'affichage du message dans le thread GUI."""
    if exc_type is not None and issubclass(exc_type, KeyboardInterrupt):
        return
    details = "".join(traceback.format_exception(exc_type, exc, tb))
    log.error("Exception non gérée %s:\n%s", where, details)
    if _notifier is not None:
        try:
            _notifier.error.emit(f"{exc_type.__name__ if exc_type else 'Erreur'} : {exc}", details)
        except RuntimeError:
            pass
    else:
        sys.__stderr__ and sys.__stderr__.write(details)


def _excepthook(t, e, tb):
    report(t, e, tb, "(thread principal)")


def _thread_hook(args):
    report(args.exc_type, args.exc_value, args.exc_traceback, f"(thread {args.thread.name if args.thread else '?'})")


def _qt_handler(mode, context, message):
    from PySide6.QtCore import QtMsgType
    if "propagateSizeHints" in message:
        return
    level = {QtMsgType.QtDebugMsg: logging.DEBUG, QtMsgType.QtInfoMsg: logging.INFO,
             QtMsgType.QtWarningMsg: logging.WARNING, QtMsgType.QtCriticalMsg: logging.ERROR,
             QtMsgType.QtFatalMsg: logging.CRITICAL}.get(mode, logging.WARNING)
    log.log(level, "Qt: %s", message)


def install(app) -> Path:
    """À appeler après la création de QApplication, dans le thread GUI."""
    global _notifier
    path = setup_logging()
    _notifier = _make_notifier()
    sys.excepthook = _excepthook
    threading.excepthook = _thread_hook
    from PySide6.QtCore import qInstallMessageHandler
    qInstallMessageHandler(_qt_handler)
    return path
