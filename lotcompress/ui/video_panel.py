"""Onglet Vidéos : réglages (préréglage, codec, qualité, résolution, GPU) et estimation."""
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal, QObject, QRunnable, QThreadPool, QTimer
from PySide6.QtWidgets import (QGroupBox, QFormLayout, QComboBox, QSlider, QLabel, QHBoxLayout,
                               QWidget, QCheckBox, QVBoxLayout)

from .. import config
from ..core.errors import describe
from ..image.estimator import human_size
from ..presets import VIDEO_PRESETS, VideoSettings

RESOLUTIONS = [("Résolution d'origine", None), ("2160 px (4K)", 3840), ("1920 px (Full HD)", 1920),
               ("1280 px (HD)", 1280), ("854 px (480p)", 854)]


class _Sig(QObject):
    gpu = Signal(str)                 # famille détectée
    info = Signal(int, object, str)   # génération, VideoInfo ou None, erreur


class _Call(QRunnable):
    def __init__(self, fn):
        super().__init__(); self.fn = fn

    def run(self):
        try:
            self.fn()
        except RuntimeError:  # Fenêtre déjà détruite (fermeture pendant le calcul)
            pass


class VideoSettingsPanel(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False
        self._target = None
        self._pad = None
        self._fps = None
        self._family = "cpu"
        self._info = None
        self._path: Optional[Path] = None
        self._gen = 0
        self._sig = _Sig()
        self._sig.gpu.connect(self._on_gpu)
        self._sig.info.connect(self._on_info)
        self._pool = QThreadPool(self); self._pool.setMaxThreadCount(1)

        lay = QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        box = QGroupBox("Réglages vidéos"); f = QFormLayout(box)
        self.preset = QComboBox(); self.preset.addItems(VIDEO_PRESETS.keys())
        f.addRow("Préréglage", self.preset)
        self.codec = QComboBox(); self.codec.addItem("H.264 (compatible partout)", "h264")
        self.codec.addItem("H.265 / HEVC (plus léger)", "h265")
        f.addRow("Codec", self.codec)
        row = QWidget(); h = QHBoxLayout(row); h.setContentsMargins(0, 0, 0, 0)
        self.quality = QSlider(Qt.Horizontal); self.quality.setRange(1, 100)
        self.quality_lbl = QLabel(""); self.quality_lbl.setMinimumWidth(30)
        h.addWidget(self.quality); h.addWidget(self.quality_lbl)
        f.addRow("Qualité", row)
        self.resolution = QComboBox()
        for label, val in RESOLUTIONS:
            self.resolution.addItem(label, val)
        f.addRow("Taille max", self.resolution)
        self.gpu = QCheckBox("Accélération GPU")
        self.gpu.setChecked(True)
        self.gpu_lbl = QLabel("Détection…"); self.gpu_lbl.setObjectName("muted")
        g = QWidget(); gh = QHBoxLayout(g); gh.setContentsMargins(0, 0, 0, 0)
        gh.addWidget(self.gpu); gh.addWidget(self.gpu_lbl); gh.addStretch()
        f.addRow(g)
        self.mode_lbl = QLabel(""); self.mode_lbl.setObjectName("muted"); self.mode_lbl.setWordWrap(True)
        f.addRow(self.mode_lbl)
        box.setMinimumWidth(320)

        info = QGroupBox("Vidéo sélectionnée"); v = QVBoxLayout(info)
        self.info_lbl = QLabel("Sélectionnez une vidéo dans la file pour voir l'estimation.")
        self.info_lbl.setWordWrap(True); self.info_lbl.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.info_lbl.setTextFormat(Qt.RichText)
        v.addWidget(self.info_lbl); v.addStretch()
        lay.addWidget(box); lay.addWidget(info, 1)

        self.preset.currentTextChanged.connect(self._apply_preset)
        self.quality.valueChanged.connect(lambda val: self.quality_lbl.setText(str(val)))
        for sig in (self.quality.valueChanged, self.codec.currentIndexChanged,
                    self.resolution.currentIndexChanged, self.gpu.toggled):
            sig.connect(self._user_changed)
        self.changed.connect(self._refresh_estimate)
        self._apply_preset(self.preset.currentText())
        self._pool.start(_Call(self._detect_gpu))

    # -- Détection GPU (en arrière-plan : quelques encodages de test)
    def _detect_gpu(self):
        from ..video.gpu import detected_family
        try:
            fam = detected_family()
        except Exception:
            fam = "cpu"
        self._sig.gpu.emit(fam)

    def _on_gpu(self, fam: str):
        from ..video.gpu import LABELS
        self._family = fam
        if config.ffmpeg_path() is None:
            self.gpu_lbl.setText("FFmpeg introuvable (dossier bin/)")
        else:
            self.gpu_lbl.setText(LABELS[fam])
        self.gpu.setEnabled(fam != "cpu")
        if fam == "cpu":
            self.gpu.setChecked(False)

    def _apply_preset(self, name: str):
        p = VIDEO_PRESETS[name]
        self._loading = True
        self.quality.setValue(p.quality)
        self.codec.setCurrentIndex(max(0, self.codec.findData(p.codec)))
        self.resolution.setCurrentIndex(max(0, self.resolution.findData(p.max_long_side)))
        self._target, self._pad, self._fps = p.target_bytes, p.pad_to, p.fps_cap
        self.quality.setEnabled(not p.target_bytes)
        self.resolution.setEnabled(not p.pad_to)
        txt = []
        if p.pad_to:
            txt.append(f"Format vertical {p.pad_to[0]}×{p.pad_to[1]} (bandes noires si besoin)")
        if p.fps_cap:
            txt.append(f"{p.fps_cap} images/s max")
        if p.target_bytes:
            txt.append(f"Débit calculé pour rester sous {human_size(p.target_bytes)}")
        txt.append(f"Audio AAC {p.audio_bitrate} kbit/s")
        self._audio = p.audio_bitrate
        self.mode_lbl.setText(" · ".join(txt))
        self._loading = False
        self.changed.emit()

    def _user_changed(self, *_):
        if not self._loading:
            self.changed.emit()

    def settings(self) -> VideoSettings:
        return VideoSettings(codec=self.codec.currentData(), quality=self.quality.value(),
                             max_long_side=self.resolution.currentData(), pad_to=self._pad,
                             fps_cap=self._fps, audio_bitrate=self._audio, target_bytes=self._target,
                             use_gpu=self.gpu.isChecked())

    # -- Estimation pour la vidéo sélectionnée
    def set_video(self, path: Optional[Path]):
        self._path, self._info = path, None
        if path is None:
            self.info_lbl.setText("Sélectionnez une vidéo dans la file pour voir l'estimation.")
            return
        self.info_lbl.setText("Analyse…")
        self._gen += 1
        gen = self._gen

        def job():
            from ..video.ffmpeg_tools import probe
            try:
                self._sig.info.emit(gen, probe(path), "")
            except Exception as e:
                self._sig.info.emit(gen, None, describe(e))
        self._pool.start(_Call(job))

    def _on_info(self, gen, info, err):
        if gen != self._gen:
            return
        if info is None:
            self.info_lbl.setText(f"<b>{self._path.name}</b><br>Analyse impossible : {err}")
            return
        self._info = info
        self._refresh_estimate()

    def _refresh_estimate(self):
        info = self._info
        if info is None or self._path is None:
            return
        from ..video.compressor import estimate_size, output_dimensions
        s = self.settings()
        est = estimate_size(info, s)
        w, h = output_dimensions(info, s)
        m, sec = divmod(int(info.duration), 60)
        audio = f"{info.audio_codec}" if info.has_audio else "aucune"
        self.info_lbl.setText(
            f"<b>{self._path.name}</b><br>"
            f"Durée : {m} min {sec:02d} s · {info.width}×{info.height} · {info.fps:.0f} im/s<br>"
            f"Vidéo : {info.video_codec} · audio : {audio}<br>"
            f"Taille d'origine : {human_size(info.size)}<br><br>"
            f"Sortie : {w}×{h} {'H.265' if s.codec == 'h265' else 'H.264'} (MP4)<br>"
            f"<b>Taille estimée : ≈ {human_size(est)}</b> "
            f"<span>(débit × durée, approximatif)</span>")
