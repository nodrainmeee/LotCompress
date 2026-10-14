# -*- mode: python ; coding: utf-8 -*-
# Build : pyinstaller lotcompress.spec   (sortie : dist/LotCompress/LotCompress.exe)
# assets/ et bin/ sont copiés à la racine du bundle (sys._MEIPASS) : config.py les y retrouve.
import os
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

datas = [("assets", "assets"), ("LICENCES.txt", ".")] + collect_data_files("pillow_heif")
binaries = collect_dynamic_libs("pillow_heif")
# Exécutables externes (ffmpeg.exe, ffprobe.exe, exiftool.exe) -> bin/ du bundle
for name in ("ffmpeg.exe", "ffprobe.exe", "exiftool.exe"):
    if os.path.isfile(os.path.join("bin", name)):
        binaries.append((os.path.join("bin", name), "bin"))
# Autres fichiers de bin/, sous-dossiers compris : bin/exiftool_files/ (indispensable à exiftool.exe), README
for dirpath, _, files in os.walk("bin"):
    for f in files:
        if f not in ("ffmpeg.exe", "ffprobe.exe", "exiftool.exe"):
            datas.append((os.path.join(dirpath, f), dirpath))

a = Analysis(["main.py"], pathex=[], binaries=binaries, datas=datas,
             hiddenimports=["pillow_heif"], excludes=["tkinter"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="LotCompress", icon="assets/icon.ico",
          console=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="LotCompress")
