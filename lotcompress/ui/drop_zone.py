"""Zone de glisser-déposer (fichiers et dossiers)."""
from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QPushButton, QHBoxLayout, QFileDialog


class DropZone(QFrame):
    paths_dropped = Signal(list)  # list[Path]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(130)
        lay = QVBoxLayout(self)
        title = QLabel("Glissez-déposez vos images, vidéos ou dossiers ici")
        title.setObjectName("dropTitle")
        title.setAlignment(Qt.AlignCenter)
        sub = QLabel("Images : JPG, PNG, WebP, HEIC, BMP, TIFF · Vidéos : MP4, MOV, MKV, AVI, WebM, M4V, 3GP, WMV — sous-dossiers inclus")
        sub.setObjectName("muted")
        sub.setAlignment(Qt.AlignCenter)
        btns = QHBoxLayout()
        bf = QPushButton("Ajouter des fichiers…")
        bd = QPushButton("Ajouter un dossier…")
        bf.clicked.connect(self._pick_files)
        bd.clicked.connect(self._pick_dir)
        btns.addStretch(); btns.addWidget(bf); btns.addWidget(bd); btns.addStretch()
        lay.addStretch(); lay.addWidget(title); lay.addWidget(sub); lay.addLayout(btns); lay.addStretch()

    def _pick_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Choisir des fichiers", "",
            "Médias (*.jpg *.jpeg *.png *.webp *.heic *.heif *.bmp *.tif *.tiff *.mp4 *.mov *.mkv *.avi *.webm *.m4v *.3gp *.wmv);;Tous les fichiers (*)")
        if files:
            self.paths_dropped.emit([Path(f) for f in files])

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Choisir un dossier")
        if d:
            self.paths_dropped.emit([Path(d)])

    def _set_active(self, on: bool):
        self.setProperty("active", on)
        self.style().unpolish(self); self.style().polish(self)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction(); self._set_active(True)

    def dragLeaveEvent(self, e):
        self._set_active(False)

    def dropEvent(self, e):
        self._set_active(False)
        paths = [Path(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.paths_dropped.emit(paths)
        e.acceptProposedAction()
