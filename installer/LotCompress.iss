; LotCompress — script Inno Setup 6
; Compilation locale (depuis le dossier du projet, après « pyinstaller lotcompress.spec ») :
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DMyAppVersion=1.0.0 installer\LotCompress.iss
; Sans /DMyAppVersion, la version par défaut ci-dessous est utilisée.
; Résultat : installer\Output\LotCompress-Setup.exe

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#define MyAppName "LotCompress"
#define MyAppPublisher "LotCompress"
#define MyAppExeName "LotCompress.exe"

[Setup]
AppId={{6F1C2B9E-4A7D-4C1E-9B3A-2D5E8F7A1C40}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}
; Installation par utilisateur, sans droits administrateur
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
LicenseFile=..\LICENCES.txt
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}
OutputDir=Output
OutputBaseFilename=LotCompress-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Contenu complet du build PyInstaller onedir (LotCompress.exe + _internal\ : Qt, assets, bin, LICENCES.txt)
Source: "..\dist\LotCompress\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Copie lisible des licences à la racine de l'installation
Source: "..\LICENCES.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autoprograms}\Licences de {#MyAppName}"; Filename: "{app}\LICENCES.txt"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Lancer {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Journaux uniquement : les profils de métadonnées et réglages de l'utilisateur sont conservés
Type: filesandordirs; Name: "{localappdata}\LotCompress\logs"
Type: dirifempty; Name: "{localappdata}\LotCompress"
Type: dirifempty; Name: "{app}"
