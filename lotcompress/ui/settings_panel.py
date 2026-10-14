"""Panneau de réglages images : préréglage, qualité, redimensionnement, conversion."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QGroupBox, QFormLayout, QComboBox, QSlider, QLabel, QHBoxLayout,
                               QWidget, QCheckBox, QSpinBox)

from ..presets import PRESETS, DEFAULT_PRESET, ImageSettings

FORMATS = [("Conserver le format", "keep"), ("JPG", "JPEG"), ("WebP", "WEBP")]


class SettingsPanel(QGroupBox):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__("Réglages images", parent)
        self._loading = False
        self._max_bytes = None
        f = QFormLayout(self)

        self.preset = QComboBox(); self.preset.addItems(PRESETS.keys())
        f.addRow("Préréglage", self.preset)

        row = QWidget(); h = QHBoxLayout(row); h.setContentsMargins(0, 0, 0, 0)
        self.quality = QSlider(Qt.Horizontal); self.quality.setRange(1, 100)
        self.quality_lbl = QLabel("80"); self.quality_lbl.setMinimumWidth(30)
        h.addWidget(self.quality); h.addWidget(self.quality_lbl)
        f.addRow("Qualité", row)

        self.resize_chk = QCheckBox("Redimensionner")
        f.addRow(self.resize_chk)
        dims = QWidget(); h2 = QHBoxLayout(dims); h2.setContentsMargins(0, 0, 0, 0)
        self.max_w = QSpinBox(); self.max_h = QSpinBox()
        for sb in (self.max_w, self.max_h):
            sb.setRange(16, 20000); sb.setSuffix(" px")
        h2.addWidget(QLabel("L max")); h2.addWidget(self.max_w)
        h2.addWidget(QLabel("H max")); h2.addWidget(self.max_h)
        f.addRow(dims)

        self.fmt = QComboBox()
        for label, val in FORMATS:
            self.fmt.addItem(label, val)
        f.addRow("Convertir en", self.fmt)

        self.preset.currentTextChanged.connect(self._apply_preset)
        self.quality.valueChanged.connect(lambda v: self.quality_lbl.setText(str(v)))
        for sig in (self.quality.valueChanged, self.resize_chk.toggled, self.max_w.valueChanged,
                    self.max_h.valueChanged, self.fmt.currentIndexChanged):
            sig.connect(self._user_changed)
        self.resize_chk.toggled.connect(dims.setEnabled)
        self._apply_preset(DEFAULT_PRESET)
        self.preset.setCurrentText(DEFAULT_PRESET)

    def _apply_preset(self, name: str):
        p = PRESETS[name]
        self._loading = True
        self.quality.setValue(p.quality)
        self.resize_chk.setChecked(bool(p.max_width or p.max_height))
        self.max_w.setValue(p.max_width or 1920); self.max_h.setValue(p.max_height or 1920)
        self.fmt.setCurrentIndex(max(0, self.fmt.findData(p.out_format)))
        self._max_bytes = p.max_bytes
        self._loading = False
        self.changed.emit()

    def _user_changed(self, *_):
        if self._loading:
            return
        self.changed.emit()

    def settings(self) -> ImageSettings:
        r = self.resize_chk.isChecked()
        return ImageSettings(quality=self.quality.value(),
                             max_width=self.max_w.value() if r else None,
                             max_height=self.max_h.value() if r else None,
                             out_format=self.fmt.currentData(),
                             max_bytes=self._max_bytes)
