"""Fenêtre principale de LotCompress."""
from pathlib import Path

from PySide6.QtCore import Qt, QSettings, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QAction
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                               QProgressBar, QSplitter, QMessageBox, QApplication, QTabWidget,
                               QCheckBox, QComboBox, QFileDialog)

from .. import config, __version__
from ..core.scanner import scan
from ..core.job_queue import JobQueue
from ..core.models import Result, Status
from ..image.estimator import human_size
from . import theme
from .drop_zone import DropZone
from .settings_panel import SettingsPanel
from .preview import PreviewPanel
from .queue_view import QueueView
from .video_panel import VideoSettingsPanel
from .metadata_panel import MetadataPanel


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{config.APP_NAME} {__version__} — Compression d'images et de vidéos par lot")
        self.resize(1200, 780)
        self.queue = JobQueue(self)
        self._saved = 0
        self._done = 0
        self._total = 0

        central = QWidget(); root = QVBoxLayout(central)
        # En-tête
        head = QHBoxLayout()
        title = QLabel("LotCompress"); title.setObjectName("appTitle")
        head.addWidget(title); head.addStretch()
        self.theme_btn = QPushButton(); self.theme_btn.clicked.connect(self._toggle_theme)
        head.addWidget(self.theme_btn)
        root.addLayout(head)

        self.drop = DropZone(); root.addWidget(self.drop)

        # Onglets de réglages : Images / Vidéos / Métadonnées (étape 4)
        self.tabs = tabs = QTabWidget()
        img_tab = QWidget(); il = QHBoxLayout(img_tab); il.setContentsMargins(0, 6, 0, 0)
        split = QSplitter(Qt.Horizontal)
        self.settings_panel = SettingsPanel(); self.settings_panel.setMinimumWidth(320)
        self.preview = PreviewPanel()
        split.addWidget(self.settings_panel); split.addWidget(self.preview)
        split.setStretchFactor(1, 1)
        il.addWidget(split)
        tabs.addTab(img_tab, "Images")
        vid_tab = QWidget(); vl = QVBoxLayout(vid_tab); vl.setContentsMargins(0, 6, 0, 0)
        self.video_panel = VideoSettingsPanel(); vl.addWidget(self.video_panel)
        tabs.addTab(vid_tab, "Vidéos")
        meta_tab = QWidget(); ml = QVBoxLayout(meta_tab); ml.setContentsMargins(0, 6, 0, 0)
        self.meta_panel = MetadataPanel(); ml.addWidget(self.meta_panel)
        tabs.addTab(meta_tab, "Métadonnées")

        vsplit = QSplitter(Qt.Vertical)
        vsplit.addWidget(tabs)
        self.table = QueueView(); vsplit.addWidget(self.table)
        vsplit.setStretchFactor(0, 3); vsplit.setStretchFactor(1, 2)
        root.addWidget(vsplit, 1)

        # Barre d'actions
        bar = QHBoxLayout()
        self.progress = QProgressBar(); self.progress.setRange(0, 100); self.progress.setValue(0)
        self.saved_lbl = QLabel("Espace gagné : 0 o"); self.saved_lbl.setObjectName("savedLabel")
        self.overwrite = QCheckBox("Écraser les originaux"); self.overwrite.setObjectName("danger")
        self.overwrite.setToolTip("Par défaut, les fichiers vont dans un dossier « Compressés » à côté des originaux.")
        self.clear_btn = QPushButton("Vider la liste")
        self.cancel_btn = QPushButton("Annuler"); self.cancel_btn.setEnabled(False)
        self.start_btn = QPushButton("Compresser"); self.start_btn.setObjectName("primary")
        # Dossier de sortie : « Compressés » à côté des fichiers (défaut) ou dossier personnalisé
        self.out_combo = QComboBox()
        self.out_combo.addItem("Sortie : « Compressés » à côté", "")
        self.out_combo.addItem("Sortie : choisir un dossier…", "__choose__")
        self._custom_out = ""
        bar.addWidget(self.progress, 1); bar.addWidget(self.saved_lbl); bar.addWidget(self.out_combo)
        bar.addWidget(self.overwrite)
        bar.addWidget(self.clear_btn); bar.addWidget(self.cancel_btn); bar.addWidget(self.start_btn)
        root.addLayout(bar)
        self.setCentralWidget(central)
        self.statusBar().showMessage("Prêt")

        # Menu Aide › À propos
        about = QAction("À propos de LotCompress", self); about.triggered.connect(self.show_about)
        lic = QAction("Licences (LICENCES.txt)", self); lic.triggered.connect(self.open_licenses)
        logs = QAction("Ouvrir le dossier des journaux", self); logs.triggered.connect(self.open_logs)
        aide = self.menuBar().addMenu("Aide")
        aide.addAction(about); aide.addAction(lic); aide.addAction(logs)

        # Outils externes : désactivation des fonctions concernées
        self.missing = config.missing_tools()
        self.has_ffmpeg = "FFmpeg" not in self.missing and "FFprobe" not in self.missing
        self.has_exiftool = "ExifTool" not in self.missing
        if not self.has_ffmpeg:
            self.tabs.setTabEnabled(1, False)
            self.tabs.setTabToolTip(1, "FFmpeg / FFprobe introuvables (dossier bin/)")
            self.meta_panel.language.setEnabled(False)
            self.meta_panel.language.setToolTip("Nécessite FFmpeg")
        if not self.has_exiftool:
            self.tabs.setTabEnabled(2, False)
            self.tabs.setTabToolTip(2, "ExifTool introuvable (dossier bin/)")
        if self.missing:
            QTimer.singleShot(300, self._warn_missing_tools)

        # Connexions
        self.drop.paths_dropped.connect(self.add_paths)
        self.table.itemSelectionChanged.connect(lambda: self._update_preview(switch_tab=True))
        self.settings_panel.changed.connect(self._update_preview)
        self.start_btn.clicked.connect(self.start)
        self.cancel_btn.clicked.connect(self.cancel)
        self.clear_btn.clicked.connect(self._clear)
        self.meta_panel.apply_requested.connect(self.start_metadata)
        self.out_combo.activated.connect(self._on_out_combo)
        s = self.queue.signals
        s.started.connect(self.table.set_started)
        s.progress.connect(self.table.set_progress)
        s.finished.connect(self._on_result)
        s.all_done.connect(self._on_all_done)
        self._refresh_theme_btn()
        self._restore_settings()
        self.settings_panel.changed.connect(self._save_settings)
        self.video_panel.changed.connect(self._save_settings)

    # ---- Fichiers -------------------------------------------------------
    def add_paths(self, paths: list[Path]):
        res = scan(paths)
        if not self.has_ffmpeg:  # Vidéos refusées proprement si FFmpeg manque
            vids = [t for t in res.tasks if t.kind == "video"]
            res.tasks = [t for t in res.tasks if t.kind != "video"]
            res.skipped += [t.source for t in vids]
        before = self.table.rowCount()
        self.table.add_tasks(res.tasks)
        added = self.table.rowCount() - before
        n_vid = sum(1 for t in self.table.tasks[before:] if t.kind == "video")
        msg = f"{added - n_vid} image(s) et {n_vid} vidéo(s) ajoutée(s)"
        if res.skipped:
            names = ", ".join(p.name for p in res.skipped[:5]) + ("…" if len(res.skipped) > 5 else "")
            why = "format non pris en charge" if self.has_ffmpeg else "format non pris en charge ou vidéo sans FFmpeg"
            msg += f" — {len(res.skipped)} fichier(s) ignoré(s) ({why}) : {names}"
        self.statusBar().showMessage(msg, 10000)
        if added and not self.table.selectedItems():
            self.table.selectRow(before)

    def _clear(self):
        if self.queue.running:
            return
        self.table.clear_all(); self.preview.request(None, self.settings_panel.settings())
        self._reset_counters()

    def _update_preview(self, switch_tab: bool = False):
        rows = self.table.selectionModel().selectedRows()
        task = self.table.task_at(rows[0].row()) if rows else None
        stay = self.tabs.currentIndex() == 2  # Onglet Métadonnées : on y reste
        if switch_tab:
            self.meta_panel.set_file(task.source if task else None)
        if task and task.kind == "video":
            if switch_tab:  # Nouvelle sélection : analyse de la vidéo et onglet Vidéos
                self.video_panel.set_video(task.source)
                self.preview.request(None, self.settings_panel.settings())
                stay or self.tabs.setCurrentIndex(1)
        else:
            self.preview.request(task.source if task else None, self.settings_panel.settings())
            if task and switch_tab:
                self.video_panel.set_video(None)
                stay or self.tabs.setCurrentIndex(0)

    # ---- Traitement -----------------------------------------------------
    def _reset_counters(self):
        self._saved = self._done = self._total = 0
        self.progress.setValue(0); self.saved_lbl.setText("Espace gagné : 0 o")

    def start(self):
        if self.queue.running:
            return
        tasks = self.table.pending_tasks()
        if not tasks:
            self.statusBar().showMessage("Aucun fichier à traiter. Ajoutez des images ou des vidéos.", 5000); return
        settings = self.settings_panel.settings().with_(overwrite=self.overwrite.isChecked(),
                                                         output_dir=self.output_dir())
        if settings.overwrite:
            r = QMessageBox.warning(
                self, "Écraser les originaux ?",
                f"Les {len(tasks)} fichier(s) originaux seront remplacés définitivement.\n"
                "Cette action est irréversible. Continuer ?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                return
        self._reset_counters(); self._total = len(tasks)
        self.table.reset_for_run(tasks)
        self._set_running(True)
        self.queue.start(tasks, settings, self.video_panel.settings())

    def start_metadata(self):
        """Applique les opérations de l'onglet Métadonnées à tous les fichiers de la liste."""
        if self.queue.running:
            return
        tasks = self.table.tasks[:]
        if not tasks:
            self.statusBar().showMessage("Aucun fichier dans la liste.", 5000); return
        try:
            ops = self.meta_panel.ops(); ops.validate()
        except Exception as e:
            QMessageBox.warning(self, "Métadonnées", str(e)); return
        if ops.is_empty():
            self.statusBar().showMessage("Aucune opération de métadonnées sélectionnée.", 5000); return
        ops.overwrite = self.overwrite.isChecked()
        ops.output_dir = self.output_dir()
        if ops.overwrite and QMessageBox.warning(
                self, "Écraser les originaux ?",
                f"Les métadonnées de {len(tasks)} fichier(s) originaux seront modifiées définitivement.\n"
                "Continuer ?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self._reset_counters(); self._total = len(tasks)
        self.table.reset_for_run(tasks)
        self._set_running(True)
        self.queue.start_metadata(tasks, ops)

    def cancel(self):
        self.queue.cancel()
        self.cancel_btn.setEnabled(False)
        self.statusBar().showMessage("Annulation… les fichiers en cours se terminent.")

    def _on_result(self, res: Result):
        self.table.set_result(res)
        self._done += 1; self._saved += res.saved
        self.progress.setValue(int(100 * self._done / max(1, self._total)))
        self.saved_lbl.setText(f"Espace gagné : {human_size(self._saved)}")

    def _on_all_done(self):
        self._set_running(False)
        counts = {}
        for t in self.table.tasks:
            counts[t.status] = counts.get(t.status, 0) + 1
        parts = [f"{n} {s.value.lower()}" for s, n in counts.items() if n]
        self.statusBar().showMessage("Terminé : " + ", ".join(parts) +
                                     f" — espace gagné : {human_size(self._saved)}")

    def _set_running(self, on: bool):
        self.start_btn.setEnabled(not on); self.cancel_btn.setEnabled(on)
        self.clear_btn.setEnabled(not on); self.drop.setEnabled(not on)
        self.settings_panel.setEnabled(not on); self.video_panel.setEnabled(not on)
        self.overwrite.setEnabled(not on); self.meta_panel.setEnabled(not on)

    # ---- Thème ----------------------------------------------------------
    def _toggle_theme(self):
        new = "sombre" if theme.load_theme() == "clair" else "clair"
        theme.save_theme(new); theme.apply_theme(QApplication.instance(), new)
        self._refresh_theme_btn()

    def _refresh_theme_btn(self):
        self.theme_btn.setText("☀ Thème clair" if theme.load_theme() == "sombre" else "☾ Thème sombre")

    # ---- Dossier de sortie --------------------------------------------
    def output_dir(self):
        """None = « Compressés » à côté des fichiers (comportement par défaut)."""
        return self._custom_out or None if self.out_combo.currentIndex() == 2 else None

    def _set_custom_out(self, path: str):
        while self.out_combo.count() > 2:
            self.out_combo.removeItem(2)
        self._custom_out = path
        if path:
            self.out_combo.addItem(f"Sortie : {Path(path).name or path}", path)
            self.out_combo.setItemData(2, path, Qt.ToolTipRole)
            self.out_combo.setCurrentIndex(2)
        else:
            self.out_combo.setCurrentIndex(0)

    def _on_out_combo(self, idx: int):
        if self.out_combo.itemData(idx) == "__choose__":
            d = QFileDialog.getExistingDirectory(self, "Dossier de sortie", self._custom_out)
            if d:
                self._set_custom_out(d)
            else:
                self.out_combo.setCurrentIndex(2 if self._custom_out else 0)
        self._save_settings()

    # ---- Réglages persistants -----------------------------------------
    def _save_settings(self):
        q = QSettings(config.ORG_NAME, config.APP_NAME)
        sp, vp = self.settings_panel, self.video_panel
        q.setValue("image/preset", sp.preset.currentText()); q.setValue("image/quality", sp.quality.value())
        q.setValue("image/format", sp.fmt.currentData()); q.setValue("image/resize", sp.resize_chk.isChecked())
        q.setValue("image/max_w", sp.max_w.value()); q.setValue("image/max_h", sp.max_h.value())
        q.setValue("video/preset", vp.preset.currentText()); q.setValue("video/quality", vp.quality.value())
        q.setValue("video/codec", vp.codec.currentData())
        q.setValue("video/resolution", vp.resolution.currentIndex())
        q.setValue("output/custom_dir", self._custom_out)
        q.setValue("output/use_custom", self.out_combo.currentIndex() == 2)

    def _restore_settings(self):
        q = QSettings(config.ORG_NAME, config.APP_NAME)
        sp, vp = self.settings_panel, self.video_panel

        def val(key, typ, default=None):
            v = q.value(key, default)
            try:
                if typ is bool:
                    return v in (True, "true", "1", 1)
                return typ(v) if v is not None else default
            except (TypeError, ValueError):
                return default
        try:
            if q.contains("image/preset") and sp.preset.findText(q.value("image/preset")) >= 0:
                sp.preset.setCurrentText(q.value("image/preset"))
                sp.quality.setValue(val("image/quality", int, sp.quality.value()))
                sp.fmt.setCurrentIndex(max(0, sp.fmt.findData(q.value("image/format"))))
                sp.resize_chk.setChecked(val("image/resize", bool))
                sp.max_w.setValue(val("image/max_w", int, sp.max_w.value()))
                sp.max_h.setValue(val("image/max_h", int, sp.max_h.value()))
            if q.contains("video/preset") and vp.preset.findText(q.value("video/preset")) >= 0:
                vp.preset.setCurrentText(q.value("video/preset"))
                vp.quality.setValue(val("video/quality", int, vp.quality.value()))
                vp.codec.setCurrentIndex(max(0, vp.codec.findData(q.value("video/codec"))))
                idx = val("video/resolution", int, -1)
                if 0 <= idx < vp.resolution.count():
                    vp.resolution.setCurrentIndex(idx)
            custom = q.value("output/custom_dir", "") or ""
            if custom and Path(custom).is_dir():
                self._set_custom_out(custom)
                if not val("output/use_custom", bool):
                    self.out_combo.setCurrentIndex(0)
        except Exception:  # Réglages corrompus : on garde les valeurs par défaut
            pass

    # ---- Outils, à propos, journaux ----------------------------------
    def _warn_missing_tools(self):
        lines = []
        if not self.has_ffmpeg:
            lines.append("• Vidéos désactivées (FFmpeg/FFprobe absents) ; langue audio indisponible.")
        if not self.has_exiftool:
            lines.append("• Onglet Métadonnées désactivé (ExifTool absent).")
        box = QMessageBox(QMessageBox.Warning, "Outils manquants",
                          "Outil(s) introuvable(s) : " + ", ".join(self.missing) + "\n\n" + "\n".join(lines) +
                          "\n\nPlacez ffmpeg.exe, ffprobe.exe et exiftool.exe (avec exiftool_files) dans le "
                          "dossier bin/ de LotCompress, puis relancez. La compression d'images reste disponible.",
                          QMessageBox.Ok, self)
        box.setModal(False); box.open()  # Non bloquant
        self._tools_box = box

    def show_about(self):
        from .. import __version__ as v
        box = QMessageBox(self)
        box.setWindowTitle("À propos de LotCompress")
        box.setIconPixmap(self.windowIcon().pixmap(64, 64))
        box.setText(f"<b>LotCompress {v}</b><br>Compression d'images et de vidéos par lot, "
                    "gestion des métadonnées.")
        box.setInformativeText(
            "Composants tiers :<br>• FFmpeg (GPL) — ffmpeg.org<br>• ExifTool (Artistic/GPL) — exiftool.org"
            "<br>• Qt / PySide6 (LGPLv3) — qt.io<br>• Pillow (MIT-CMU/HPND), pillow-heif (BSD-3, libheif LGPL)"
            "<br>• PyInstaller (bootloader : GPL avec exception)<br><br>Texte complet : LICENCES.txt")
        btn = box.addButton("Ouvrir LICENCES.txt", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Close)
        box.exec()
        if box.clickedButton() is btn:
            self.open_licenses()

    def open_licenses(self):
        p = config.LICENSES_PATH
        if not p.exists():
            QMessageBox.warning(self, "Licences", f"Fichier introuvable : {p}"); return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def open_logs(self):
        d = config.log_dir(); d.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    def closeEvent(self, e):
        self._save_settings()
        if self.queue.running:
            self.queue.cancel(); self.queue.wait(5000)
        super().closeEvent(e)
