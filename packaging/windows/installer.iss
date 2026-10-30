; Inno Setup script for PriorityDateTracker-Setup.exe. Build after PyInstaller, from the repository root:
;   iscc /DAppVersion=0.1.0 packaging\windows\installer.iss
; Installs for the current Windows user only, so no administrator password is needed.
; Office data lives in Documents\Priority Date Tracker and is never removed by uninstalling.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F3B2D1E-8C4A-4E7B-9A51-2D0C7E5B9F14}
AppName=Priority Date Tracker
AppVersion={#AppVersion}
AppPublisher=Priority Date Tracker
DefaultDirName={localappdata}\Programs\Priority Date Tracker
DefaultGroupName=Priority Date Tracker
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=PriorityDateTracker-Setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\PriorityDateTracker.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Put a Priority Date Tracker icon on the desktop"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\..\dist\PriorityDateTracker\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
Name: "{userdocs}\Priority Date Tracker"; Flags: uninsneveruninstall

[Icons]
Name: "{group}\Priority Date Tracker"; Filename: "{app}\PriorityDateTracker.exe"
Name: "{group}\Priority Date Tracker - practice with sample data"; Filename: "{app}\PriorityDateTracker.exe"; Parameters: "demo"
Name: "{group}\Priority Date Tracker - office files"; Filename: "{userdocs}\Priority Date Tracker"
Name: "{group}\Uninstall Priority Date Tracker"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Priority Date Tracker"; Filename: "{app}\PriorityDateTracker.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PriorityDateTracker.exe"; Description: "Open the Priority Date Tracker now"; Flags: nowait postinstall skipifsilent
