"""Finitions de l'application : outils manquants, gestion des erreurs, réglages persistants."""
import threading
from pathlib import Path

from lotcompress import config, crash


def _window(qapp, monkeypatch, missing=()):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)   # Jamais de boîte bloquante
    monkeypatch.setattr(QMessageBox, "open", lambda self: None)
    if "ffmpeg" in missing:
        monkeypatch.setattr(config, "ffmpeg_path", lambda: None)
    if "exiftool" in missing:
        monkeypatch.setattr(config, "exiftool_path", lambda: None)
    from lotcompress.ui.main_window import MainWindow
    return MainWindow()


def test_missing_ffmpeg_disables_video(qapp, monkeypatch, tmp_path):
    w = _window(qapp, monkeypatch, missing=("ffmpeg", "exiftool"))
    assert "FFmpeg" in w.missing and "ExifTool" in w.missing
    assert not w.tabs.isTabEnabled(1) and not w.tabs.isTabEnabled(2)
    assert not w.meta_panel.language.isEnabled()
    (tmp_path / "v.mp4").write_bytes(b"x"); (tmp_path / "i.jpg").write_bytes(b"x")
    w.add_paths([tmp_path])  # Vidéo signalée comme non prise en charge, sans plantage
    assert [t.kind for t in w.table.tasks] == ["image"]
    assert "ignoré" in w.statusBar().currentMessage()
    w.close()


def test_tools_present_tabs_enabled(qapp, monkeypatch):
    w = _window(qapp, monkeypatch)
    if not config.missing_tools():
        assert w.tabs.isTabEnabled(1) and w.tabs.isTabEnabled(2)
    w.close()


def test_settings_persist(qapp, monkeypatch, tmp_path):
    w = _window(qapp, monkeypatch)
    w.settings_panel.preset.setCurrentText("WhatsApp"); w.settings_panel.quality.setValue(42)
    w.video_panel.preset.setCurrentText("Instagram / TikTok")
    w.video_panel.codec.setCurrentIndex(w.video_panel.codec.findData("h265"))
    w._set_custom_out(str(tmp_path)); w.close()
    w2 = _window(qapp, monkeypatch)
    assert w2.settings_panel.preset.currentText() == "WhatsApp"
    assert w2.settings_panel.quality.value() == 42
    assert w2.video_panel.preset.currentText() == "Instagram / TikTok"
    assert w2.video_panel.codec.currentData() == "h265"
    assert w2.output_dir() == str(tmp_path)
    w2.out_combo.setCurrentIndex(0)
    assert w2.output_dir() is None  # Défaut : « Compressés »
    w2.close()


def test_global_error_handler_logs_and_shows(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(threading.current_thread().name) or 0)
    log_path = crash.install(qapp)

    def boom():
        raise RuntimeError("erreur de test dans un thread")
    t = threading.Thread(target=boom, name="worker-test"); t.start(); t.join()
    for _ in range(20):
        qapp.processEvents()
    for h in crash.log.handlers:
        h.flush()
    text = Path(log_path).read_text(encoding="utf-8")
    assert "erreur de test dans un thread" in text and "worker-test" in text
    assert shown == [threading.main_thread().name]  # Affiché dans le thread GUI


def test_about_and_licenses(qapp, monkeypatch):
    assert config.LICENSES_PATH.exists()
    w = _window(qapp, monkeypatch)
    w.show_about()  # exec neutralisé : ne doit pas lever
    w.close()
