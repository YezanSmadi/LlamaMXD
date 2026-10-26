; SPDX-License-Identifier: GPL-3.0-or-later
; Copyright (C) 2026 Yezan Smadi
; Inno Setup script: packs build/dist/LlamaMXD (made by packaging/build.py) into one per-user installer.
; Compile through build.py --installer, which passes AppVersion and AppNumeric.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef AppNumeric
  #define AppNumeric "0.0.0.0"
#endif

[Setup]
; Never change this AppId: it is how a newer installer recognises (and upgrades) an installed copy.
AppId={{21646A70-40C4-4B6B-9F66-F6F0A2B01409}
AppName=LlamaMXD
AppVersion={#AppVersion}
AppPublisher=Yezan Smadi
AppPublisherURL=https://github.com/YezanSmadi/LlamaMXD
AppSupportURL=https://github.com/YezanSmadi/LlamaMXD/issues
AppUpdatesURL=https://github.com/YezanSmadi/LlamaMXD/releases
VersionInfoVersion={#AppNumeric}
; Per-user install: no admin prompt, and the app can write beside itself.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=
DefaultDirName={autopf}\LlamaMXD
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
InfoBeforeFile=..\LICENSE.txt
SetupIconFile=..\build\LlamaMXD.ico
UninstallDisplayIcon={app}\LlamaMXD.exe
WizardStyle=modern
OutputDir=..\build\installer
OutputBaseFilename=LlamaMXD-Setup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
; settings.json and presets.json are never shipped: the app makes them in the user's data folder.
Source: "..\build\dist\LlamaMXD\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\LlamaMXD"; Filename: "{app}\LlamaMXD.exe"
Name: "{autodesktop}\LlamaMXD"; Filename: "{app}\LlamaMXD.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\LlamaMXD.exe"; Description: "Launch LlamaMXD"; Flags: nowait postinstall skipifsilent

[Code]
{ Uninstalling keeps the user's settings, presets and logs unless they say otherwise. }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep <> usPostUninstall then Exit;
  DataDir := ExpandConstant('{localappdata}\LlamaMXD');
  if UninstallSilent or not DirExists(DataDir) then Exit;
  if MsgBox('Also delete your LlamaMXD settings, presets and logs?' + #13#10 + DataDir,
            mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
    DelTree(DataDir, True, True, True);
end;
