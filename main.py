"""Point d'entrée de LotCompress."""
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

from lotcompress import config, crash
from lotcompress.ui.main_window import MainWindow
from lotcompress.ui import theme


def self_check() -> int:
    """« LotCompress --self-check » : affiche les chemins résolus (diagnostic du build)."""
    from lotcompress import __version__
    print(f"LotCompress {__version__} frozen={getattr(sys, 'frozen', False)}")
    for label, p in (("base", config.BASE_DIR), ("assets", config.ASSETS_DIR), ("icon", config.ICON_PATH),
                     ("themes", config.THEMES_DIR / "clair.qss"), ("licences", config.LICENSES_PATH),
                     ("bin", config.BIN_DIR), ("ffmpeg", config.ffmpeg_path()), ("ffprobe", config.ffprobe_path()),
                     ("exiftool", config.exiftool_path()), ("logs", config.log_dir())):
        print(f"{label:9} {p}  {'OK' if p and Path(p).exists() else 'ABSENT'}")
    return 0


def main() -> int:
    if "--self-check" in sys.argv:
        return self_check()
    app = QApplication(sys.argv)
    app.setOrganizationName(config.ORG_NAME)
    app.setApplicationName(config.APP_NAME)
    crash.install(app)  # Journal + gestion globale des erreurs
    if config.ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(config.ICON_PATH)))
    theme.apply_theme(app, theme.load_theme())
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
