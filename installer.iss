[Setup]
AppId=TAF Order Entry
AppName=TAF Order Entry
AppVersion=2.2.1
AppPublisher=TAF
DefaultDirName={autopf}\TAF Order Entry
DefaultGroupName=TAF Order Entry
OutputDir=.
OutputBaseFilename=TAFOrderEntry_Setup
SetupIconFile=TAF_logo.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
; All files from the one-dir PyInstaller build (exe + DLLs + Python libs)
Source: "dist\TAFOrderEntry\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; User settings — only on first install (PyInstaller 6 puts data files in _internal)
Source: "dist\TAFOrderEntry\_internal\settings.json"; DestDir: "{userappdata}\TAF Order Entry"; Flags: ignoreversion onlyifdoesntexist

[Icons]
; Use the icon embedded in the exe itself (no separate .ico needed)
Name: "{userprograms}\TAF Order Entry";           Filename: "{app}\TAFOrderEntry.exe"; IconFilename: "{app}\TAFOrderEntry.exe"; IconIndex: 0
Name: "{userprograms}\Uninstall TAF Order Entry"; Filename: "{uninstallexe}"
Name: "{userdesktop}\TAF Order Entry";            Filename: "{app}\TAFOrderEntry.exe"; IconFilename: "{app}\TAFOrderEntry.exe"; IconIndex: 0; Tasks: desktopicon

[Run]
Filename: "{app}\TAFOrderEntry.exe"; Description: "Launch TAF Order Entry"; Flags: nowait postinstall skipifsilent
