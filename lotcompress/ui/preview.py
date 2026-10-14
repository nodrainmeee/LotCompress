"""Aperçu avant/après calculé en arrière-plan, avec anti-rebond."""
from pathlib import Path
from typing import Optional

from PIL import Image
from PySide6.QtCore import Qt, QTimer, QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QGroupBox, QLabel, QGridLayout, QSizePolicy

from .. import config
from ..core.errors import describe
from ..image.estimator import estimate, human_size
from ..presets import ImageSettings


def pil_to_pixmap(img: Image.Image) -> QPixmap:
    img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    q = QImage(data, img.width, img.height, img.width * 4, QImage.Format_RGBA8888)
    return QPixmap.fromImage(q.copy())


class _Sig(QObject):
    done = Signal(int, object, str)  # génération, Estimate ou None, erreur


class _EstimateJob(QRunnable):
    def __init__(self, gen, path, settings, sig):
        super().__init__(); self.gen, self.path, self.settings, self.sig = gen, path, settings, sig

    def run(self):
        try:
            try:
                self.sig.done.emit(self.gen, estimate(self.path, self.settings), "")
            except Exception as e:
                self.sig.done.emit(self.gen, None, describe(e))
        except RuntimeError:  # Fenêtre déjà détruite
            pass


class _ImageLabel(QLabel):
    """Label qui redimensionne son pixmap en conservant les proportions."""
    def __init__(self, text):
        super().__init__(text); self._pm = None
        self.setAlignment(Qt.AlignCenter); self.setMinimumSize(160, 140)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setObjectName("previewImage")

    def set_pixmap(self, pm: Optional[QPixmap]):
        self._pm = pm; self._refresh()
        if pm is None:
            self.clear()

    def resizeEvent(self, e):
        super().resizeEvent(e); self._refresh()

    def _refresh(self):
        if self._pm:
            self.setPixmap(self._pm.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))


class PreviewPanel(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("Aperçu avant / après", parent)
        g = QGridLayout(self)
        self.before = _ImageLabel("Sélectionnez un fichier")
        self.after = _ImageLabel("")
        self.before_info = QLabel("Original"); self.after_info = QLabel("Après compression")
        for l in (self.before_info, self.after_info):
            l.setAlignment(Qt.AlignCenter)
        g.addWidget(self.before, 0, 0); g.addWidget(self.after, 0, 1)
        g.addWidget(self.before_info, 1, 0); g.addWidget(self.after_info, 1, 1)
        self._path: Optional[Path] = None
        self._settings: Optional[ImageSettings] = None
        self._gen = 0
        self._pool = QThreadPool(self); self._pool.setMaxThreadCount(1)
        self._sig = _Sig(); self._sig.done.connect(self._on_done)
        self._timer = QTimer(self); self._timer.setSingleShot(True)
        self._timer.setInterval(config.PREVIEW_DEBOUNCE_MS)
        self._timer.timeout.connect(self._launch)

    def request(self, path: Optional[Path], settings: ImageSettings):
        """Demande un recalcul (anti-rebond : seul le dernier appel compte)."""
        self._path, self._settings = path, settings
        if path is None:
            self.before.set_pixmap(None); self.after.set_pixmap(None)
            self.before.setText("Sélectionnez un fichier"); return
        self.after_info.setText("Calcul…")
        self._timer.start()

    def _launch(self):
        self._gen += 1
        self._pool.start(_EstimateJob(self._gen, self._path, self._settings, self._sig))

    def _on_done(self, gen, est, err):
        if gen != self._gen:
            return  # Résultat obsolète
        if est is None:
            self.before.set_pixmap(None); self.after.set_pixmap(None)
            self.before.setText("Aperçu impossible"); self.after_info.setText(err)
            return
        self.before.set_pixmap(pil_to_pixmap(est.original))
        self.after.set_pixmap(pil_to_pixmap(est.compressed))
        self.before_info.setText(f"Original : {human_size(est.original_size)}")
        pct = 100 * (1 - est.estimated_size / est.original_size) if est.original_size else 0
        w, h = est.dimensions
        self.after_info.setText(f"Estimé : {human_size(est.estimated_size)} ({pct:.0f} % gagné) — "
                                f"{est.out_format} {w}×{h}")
