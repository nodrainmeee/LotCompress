# LotCompress 1.0.0

Compresseur d'images et de vidéos par lot pour Windows, avec gestion des métadonnées
(PySide6, Pillow + pillow-heif, FFmpeg, ExifTool).

## Installation (utilisateurs)
1. Téléchargez **LotCompress-Setup.exe** depuis la page *Releases* du dépôt GitHub.
2. Lancez-le : l'installation se fait pour votre compte, **sans droits administrateur**, dans
   `%LOCALAPPDATA%\Programs\LotCompress`. Un raccourci est créé dans le menu Démarrer
   (raccourci Bureau en option).
3. FFmpeg et ExifTool sont déjà inclus. Rien d'autre à installer.
4. Désinstallation : *Paramètres › Applications › LotCompress*. Les journaux sont supprimés ;
   vos profils de métadonnées et réglages sont conservés.

Journaux en cas de problème : `%LOCALAPPDATA%\LotCompress\logs\lotcompress.log`
(menu *Aide › Ouvrir le dossier des journaux*).

## Utilisation
- Glissez-déposez des images, vidéos ou dossiers (sous-dossiers inclus). Formats non pris en
  charge ignorés et signalés.
- Onglet **Images** / **Vidéos** : préréglage, qualité, taille, format ou codec, puis **Compresser**.
- Onglet **Métadonnées** : choisissez les opérations puis **Appliquer au lot**.
- Sortie : par défaut un dossier **Compressés** à côté des fichiers (arborescence conservée), ou
  un dossier de votre choix (liste « Sortie » en bas). Les originaux ne sont modifiés que si vous
  cochez « Écraser les originaux » et confirmez.
- Vos choix (préréglages, qualités, codec, thème, dossier de sortie) sont mémorisés.
- Si FFmpeg/FFprobe ou ExifTool manquent, un message l'indique au démarrage : l'onglet concerné
  est désactivé et la compression d'images reste disponible.

## Développement
### Lancer depuis les sources
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
python main.py
```
Placez `ffmpeg.exe`, `ffprobe.exe` et `exiftool.exe` (+ `exiftool_files\`) dans `bin\`
(à défaut, ceux du PATH sont utilisés).

### Tests
```powershell
python -m pytest
```

### Build local
```powershell
pyinstaller --noconfirm lotcompress.spec
dist\LotCompress\LotCompress.exe --self-check   # vérifie les chemins assets/bin/licences
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DMyAppVersion=1.0.0 installer\LotCompress.iss
```
Résultat : `dist\LotCompress\` (application onedir) puis `installer\Output\LotCompress-Setup.exe`.
Sans `/DMyAppVersion`, le script Inno utilise 1.0.0 par défaut.

### Publier une version
1. Mettez à jour `__version__` dans `lotcompress/__init__.py` (ex. `1.0.0`).
2. Puis :
```bash
git tag v1.0.0 && git push --tags
```
Le workflow `.github/workflows/build.yml` télécharge FFmpeg (gyan.dev) et ExifTool (exiftool.org),
lance les tests, construit avec PyInstaller, compile l'installateur Inno Setup et crée la
Release GitHub avec `LotCompress-Setup.exe`. Sur les autres push / PR, l'installateur est
disponible en artefact du workflow.

## Licences
Voir `LICENCES.txt` (aussi accessible via *Aide › À propos*). FFmpeg est distribué en build GPL,
ExifTool sous licence Perl (Artistic/GPL), Qt/PySide6 sous LGPLv3.

## Vidéos
- FFmpeg est nécessaire : placez `ffmpeg.exe` et `ffprobe.exe` dans `bin/` (builds Windows : https://www.gyan.dev/ffmpeg/builds/). À défaut, LotCompress utilise ceux du PATH.
- Préréglages : Web (1920 px, H.264), Instagram/TikTok (1080×1920 avec bandes noires, 30 im/s max), WhatsApp (1280 px), Email (débit calculé pour rester sous 10 Mo).
- Codec H.264 ou H.265 (HEVC, plus léger). Sortie toujours en MP4 (lecture rapide sur le web : `+faststart`).
- Accélération GPU : NVENC (NVIDIA) ou QuickSync (Intel) si détecté par un vrai test d'encodage ; sinon le processeur (libx264/libx265).

## Métadonnées
- **ExifTool requis.** Sous Windows, téléchargez ExifTool sur https://exiftool.org (« Windows Executable »), renommez `exiftool(-k).exe` en **`exiftool.exe`** et placez-le dans `bin/` **avec son dossier `exiftool_files`** juste à côté (`bin/exiftool.exe` + `bin/exiftool_files/`). `lotcompress.spec` embarque tout le contenu de `bin/`, y compris `exiftool_files`. À défaut, l'exiftool du PATH est utilisé.
- La langue audio est écrite avec FFmpeg (remux sans réencodage) : `ffmpeg.exe` doit aussi être dans `bin/`.
- **Supprimer en un clic** : GPS, appareil (marque, modèle, objectif, n° de série, propriétaire), logiciel de montage / encodeur, commentaires, description.
- **Ajouter** : titre, description, auteur, copyright, mots-clés (EXIF/IPTC/XMP pour les images, QuickTime/Keys/XMP pour les vidéos).
- **Corriger** : date de création, orientation (EXIF pour les images, rotation pour les vidéos), langue audio (code ISO 639-2).
- **Profils** (ex. « Mes vidéos TikTok ») enregistrés en JSON dans le dossier de données de l'application et applicables à tout un lot.
- Aperçu avant/après : les changements sont calculés sur une copie temporaire du fichier sélectionné.
- Les fichiers modifiés vont dans « Compressés » ; les originaux ne sont touchés que si vous cochez « Écraser les originaux » et confirmez.
- **Interdit par conception** : LotCompress ne peut ni ajouter ni modifier la marque, le modèle ou l'objectif d'un appareil (liste noire appliquée aussi aux profils). Seule leur suppression est possible.
