"""Onglet Métadonnées : suppression, ajout, correction, profils, aperçu avant/après."""
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal, QObject, QRunnable, QThreadPool, QTimer, QDateTime
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QGroupBox, QCheckBox, QFormLayout,
                               QLineEdit, QComboBox, QDateTimeEdit, QPushButton, QTableWidget,
                               QTableWidgetItem, QHeaderView, QLabel, QScrollArea, QInputDialog,
                               QMessageBox, QAbstractItemView, QFrame)

from .. import config
from ..core.errors import describe
from ..metadata.operations import MetaOps, LANGUAGES, IMAGE_ORIENTATIONS
from ..metadata import profiles


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, list):
        return ", ".join(map(str, v))
    return str(v)


class _Sig(QObject):
    done = Signal(int, object, object, str)


class _Call(QRunnable):
    def __init__(self, fn):
        super().__init__(); self.fn = fn

    def run(self):
        try:
            self.fn()
        except RuntimeError:  # Fenêtre déjà détruite (fermeture pendant le calcul)
            pass


class MetadataPanel(QWidget):
    apply_requested = Signal()   # « Appliquer au lot »
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path: Optional[Path] = None
        self._gen = 0
        self._loading = False
        self._sig = _Sig(); self._sig.done.connect(self._on_preview)
        self._pool = QThreadPool(self); self._pool.setMaxThreadCount(1)
        self._timer = QTimer(self); self._timer.setSingleShot(True); self._timer.setInterval(500)
        self._timer.timeout.connect(self._launch_preview)

        root = QHBoxLayout(self); root.setContentsMargins(0, 0, 0, 0)
        left = QWidget(); ll = QVBoxLayout(left); ll.setContentsMargins(0, 0, 6, 0)

        # Profils
        pbox = QGroupBox("Profil"); pl = QVBoxLayout(pbox)
        self.profile = QComboBox()
        self.btn_save = QPushButton("Enregistrer…"); self.btn_ren = QPushButton("Renommer…")
        self.btn_del = QPushButton("Supprimer")
        pl.addWidget(self.profile)
        prow = QHBoxLayout()
        for b in (self.btn_save, self.btn_ren, self.btn_del):
            prow.addWidget(b)
        pl.addLayout(prow)
        ll.addWidget(pbox)

        rm = QGroupBox("Supprimer"); rl = QVBoxLayout(rm)
        self.rm_gps = QCheckBox("Position GPS")
        self.rm_camera = QCheckBox("Appareil (marque, modèle, objectif, n° de série, propriétaire)")
        self.rm_software = QCheckBox("Logiciel de montage / encodeur")
        self.rm_comments = QCheckBox("Commentaires")
        self.rm_desc = QCheckBox("Description existante")
        for c in (self.rm_gps, self.rm_camera, self.rm_software, self.rm_comments, self.rm_desc):
            rl.addWidget(c)
        ll.addWidget(rm)

        add = QGroupBox("Ajouter"); al = QFormLayout(add)
        self.title = QLineEdit(); self.description = QLineEdit(); self.author = QLineEdit()
        self.copyright = QLineEdit(); self.keywords = QLineEdit()
        self.copyright.setPlaceholderText("© 2026 Votre nom")
        self.keywords.setPlaceholderText("mots-clés séparés par des virgules")
        al.addRow("Titre", self.title); al.addRow("Description", self.description)
        al.addRow("Auteur", self.author); al.addRow("Copyright", self.copyright)
        al.addRow("Mots-clés", self.keywords)
        ll.addWidget(add)

        fix = QGroupBox("Corriger"); fl = QFormLayout(fix)
        drow = QWidget(); dh = QHBoxLayout(drow); dh.setContentsMargins(0, 0, 0, 0)
        self.date_chk = QCheckBox()
        self.date = QDateTimeEdit(QDateTime.currentDateTime()); self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd/MM/yyyy HH:mm:ss"); self.date.setEnabled(False)
        dh.addWidget(self.date_chk); dh.addWidget(self.date, 1)
        fl.addRow("Date de création", drow)
        self.orientation = QComboBox(); self.orientation.addItem("Inchangée", 0)
        for code, label in IMAGE_ORIENTATIONS.items():
            if code in (1, 3, 6, 8):
                self.orientation.addItem(label, code)
        fl.addRow("Orientation", self.orientation)
        self.language = QComboBox(); self.language.addItem("Inchangée", "")
        for code, label in LANGUAGES.items():
            self.language.addItem(f"{label} ({code})", code)
        fl.addRow("Langue audio", self.language)
        note = QLabel("Les informations d'appareil (marque, modèle, objectif) peuvent seulement être "
                      "supprimées, jamais ajoutées ni modifiées.")
        note.setObjectName("muted"); note.setWordWrap(True)
        fl.addRow(note)
        ll.addWidget(fix); ll.addStretch()

        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(left)
        scroll.setFrameShape(QFrame.NoFrame); scroll.setMinimumWidth(430)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root.addWidget(scroll)

        right = QGroupBox("Aperçu des métadonnées (avant / après)"); rl2 = QVBoxLayout(right)
        self.info = QLabel("Sélectionnez un fichier dans la file."); self.info.setObjectName("muted")
        self.only_changes = QCheckBox("Afficher uniquement les changements"); self.only_changes.setChecked(True)
        self.table = QTableWidget(0, 3); self.table.setHorizontalHeaderLabels(["Balise", "Avant", "Après"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch); hh.setSectionResizeMode(2, QHeaderView.Stretch)
        self.apply_btn = QPushButton("Appliquer au lot"); self.apply_btn.setObjectName("primary")
        bot = QHBoxLayout(); bot.addWidget(self.only_changes); bot.addStretch(); bot.addWidget(self.apply_btn)
        rl2.addWidget(self.info); rl2.addWidget(self.table, 1); rl2.addLayout(bot)
        root.addWidget(right, 1)

        # Connexions
        self.date_chk.toggled.connect(self.date.setEnabled)
        for w in (self.rm_gps, self.rm_camera, self.rm_software, self.rm_comments, self.rm_desc,
                  self.date_chk, self.only_changes):
            w.toggled.connect(self._changed)
        for w in (self.title, self.description, self.author, self.copyright, self.keywords):
            w.textChanged.connect(self._changed)
        self.date.dateTimeChanged.connect(self._changed)
        self.orientation.currentIndexChanged.connect(self._changed)
        self.language.currentIndexChanged.connect(self._changed)
        self.apply_btn.clicked.connect(self.apply_requested)
        self.btn_save.clicked.connect(self._save_profile)
        self.btn_ren.clicked.connect(self._rename_profile)
        self.btn_del.clicked.connect(self._delete_profile)
        self.profile.activated.connect(self._load_selected)
        self._reload_profiles()

    # ---------------------------------------------------------- Opérations
    def ops(self) -> MetaOps:
        kws = [k.strip() for k in self.keywords.text().split(",") if k.strip()]
        return MetaOps(remove_gps=self.rm_gps.isChecked(), remove_camera=self.rm_camera.isChecked(),
                       remove_software=self.rm_software.isChecked(),
                       remove_comments=self.rm_comments.isChecked(), remove_description=self.rm_desc.isChecked(),
                       title=self.title.text().strip(), description=self.description.text().strip(),
                       author=self.author.text().strip(), copyright=self.copyright.text().strip(),
                       keywords=kws,
                       date=self.date.dateTime().toString("yyyy:MM:dd HH:mm:ss") if self.date_chk.isChecked() else "",
                       orientation=self.orientation.currentData(), audio_language=self.language.currentData())

    def set_ops(self, o: MetaOps):
        self._loading = True
        self.rm_gps.setChecked(o.remove_gps); self.rm_camera.setChecked(o.remove_camera)
        self.rm_software.setChecked(o.remove_software); self.rm_comments.setChecked(o.remove_comments)
        self.rm_desc.setChecked(o.remove_description)
        self.title.setText(o.title); self.description.setText(o.description); self.author.setText(o.author)
        self.copyright.setText(o.copyright); self.keywords.setText(", ".join(o.keywords))
        self.date_chk.setChecked(bool(o.date))
        if o.date:
            self.date.setDateTime(QDateTime.fromString(o.date, "yyyy:MM:dd HH:mm:ss"))
        self.orientation.setCurrentIndex(max(0, self.orientation.findData(o.orientation)))
        self.language.setCurrentIndex(max(0, self.language.findData(o.audio_language)))
        self._loading = False
        self._changed()

    def _changed(self, *_):
        if self._loading:
            return
        self.changed.emit()
        if self._path:
            self.info.setText("Calcul de l'aperçu…")
            self._timer.start()

    # ---------------------------------------------------------- Profils
    def _reload_profiles(self, select: str = ""):
        self.profile.clear(); self.profile.addItem("— Aucun —", "")
        try:
            for n in profiles.list_profiles():
                self.profile.addItem(n, n)
        except Exception:
            pass
        if select:
            self.profile.setCurrentIndex(max(0, self.profile.findData(select)))

    def _load_selected(self, *_):
        name = self.profile.currentData()
        if not name:
            return
        try:
            self.set_ops(profiles.load_profile(name))
        except Exception as e:
            QMessageBox.warning(self, "Profil", f"Impossible de charger « {name} » : {describe(e)}")

    def _save_profile(self):
        name, ok = QInputDialog.getText(self, "Enregistrer le profil", "Nom du profil :",
                                        text=self.profile.currentData() or "Mes vidéos TikTok")
        if ok and name.strip():
            try:
                profiles.save_profile(name, self.ops()); self._reload_profiles(name.strip())
            except Exception as e:
                QMessageBox.warning(self, "Profil", describe(e))

    def _rename_profile(self):
        old = self.profile.currentData()
        if not old:
            return
        new, ok = QInputDialog.getText(self, "Renommer le profil", "Nouveau nom :", text=old)
        if ok and new.strip():
            try:
                profiles.rename_profile(old, new); self._reload_profiles(new.strip())
            except Exception as e:
                QMessageBox.warning(self, "Profil", describe(e))

    def _delete_profile(self):
        name = self.profile.currentData()
        if name and QMessageBox.question(self, "Supprimer le profil",
                                         f"Supprimer le profil « {name} » ?") == QMessageBox.Yes:
            profiles.delete_profile(name); self._reload_profiles()

    # ---------------------------------------------------------- Aperçu
    def set_file(self, path: Optional[Path]):
        self._path = path
        if path is None:
            self.table.setRowCount(0); self.info.setText("Sélectionnez un fichier dans la file.")
            return
        self.info.setText(f"{path.name} : lecture des métadonnées…")
        self._timer.start()

    def _launch_preview(self):
        if not self._path:
            return
        self._gen += 1
        gen, path, ops = self._gen, self._path, self.ops()

        def job():
            from ..metadata.operations import preview
            try:
                before, after = preview(path, ops)
                self._sig.done.emit(gen, before, after, "")
            except Exception as e:
                self._sig.done.emit(gen, None, None, describe(e))
        self._pool.start(_Call(job))

    def _on_preview(self, gen, before, after, err):
        if gen != self._gen:
            return
        if before is None:
            self.table.setRowCount(0); self.info.setText(f"Aperçu impossible : {err}"); return
        keys = sorted(set(before) | set(after))
        changed = [k for k in keys if before.get(k) != after.get(k)]
        rows = changed if self.only_changes.isChecked() else keys
        self.info.setText(f"{self._path.name} : {len(changed)} changement(s) sur {len(keys)} balise(s)")
        self.table.setRowCount(len(rows))
        removed, added, modified = QColor(239, 68, 68, 60), QColor(16, 185, 129, 60), QColor(217, 119, 6, 60)
        for r, k in enumerate(rows):
            b, a = before.get(k), after.get(k)
            items = [QTableWidgetItem(k), QTableWidgetItem(_fmt(b)),
                     QTableWidgetItem(_fmt(a) if a is not None else "(supprimé)")]
            if b != a:
                color = removed if a is None else added if b is None else modified
                for it in items:
                    it.setBackground(QBrush(color))
            for c, it in enumerate(items):
                it.setToolTip(it.text()); self.table.setItem(r, c, it)
