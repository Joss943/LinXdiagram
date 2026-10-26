; Installateur Windows (Inno Setup 6) : menu Démarrer, associations .lxd / .vsdx,
; installation par utilisateur sans droits administrateur.
;   iscc /DAppVersion=1.1.0 packaging\windows\linxdiagram.iss
#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif

[Setup]
AppId={{6D0B5B4E-6C1B-4B9B-9B3E-1C7A0D5F2A11}
AppName=LinXdiagram
AppVersion={#AppVersion}
AppPublisher=Josselin Lerendu
AppPublisherURL=https://joss943.github.io/LinXdiagram/
DefaultDirName={localappdata}\Programs\LinXdiagram
DefaultGroupName=LinXdiagram
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
OutputDir=..\..\dist
OutputBaseFilename=LinXdiagram-{#AppVersion}-windows-x64-setup
SetupIconFile=..\..\build\icons\LinXdiagram.ico
UninstallDisplayIcon={app}\LinXdiagram.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ChangesAssociations=yes
LicenseFile=..\..\LICENSE

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "assocvsdx"; Description: "Ouvrir les fichiers Visio (.vsdx) avec LinXdiagram"; Flags: unchecked

[Files]
Source: "..\..\dist\LinXdiagram\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\LinXdiagram"; Filename: "{app}\LinXdiagram.exe"
Name: "{autodesktop}\LinXdiagram"; Filename: "{app}\LinXdiagram.exe"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\.lxd"; ValueType: string; ValueName: ""; ValueData: "LinXdiagram.Document"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\LinXdiagram.Document"; ValueType: string; ValueName: ""; ValueData: "Dessin LinXdiagram"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\LinXdiagram.Document\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\LinXdiagram.exe,0"
Root: HKA; Subkey: "Software\Classes\LinXdiagram.Document\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\LinXdiagram.exe"" ""%1"""
Root: HKA; Subkey: "Software\Classes\.vsdx\OpenWithProgids"; ValueType: string; ValueName: "LinXdiagram.Document"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assocvsdx

[Run]
Filename: "{app}\LinXdiagram.exe"; Description: "{cm:LaunchProgram,LinXdiagram}"; Flags: nowait postinstall skipifsilent
