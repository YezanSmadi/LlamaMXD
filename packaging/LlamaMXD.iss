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
WizardStyle=modern dynamic
; The logo alone, drawn by wizard_images.py: black line art for a light wizard, white for a dark one
; (dynamic follows Windows' setting, read once at startup). One file per DPI size; Setup picks the closest.
WizardImageFile=..\build\wizard\light\side-*.png
WizardImageFileDynamicDark=..\build\wizard\dark\side-*.png
WizardSmallImageFile=..\build\wizard\light\small-*.png
WizardSmallImageFileDynamicDark=..\build\wizard\dark\small-*.png
OutputDir=..\build\installer
OutputBaseFilename=LlamaMXD-Setup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "startmenuicon"; Description: "Create a &Start Menu shortcut"; GroupDescription: "Shortcuts:"
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
; settings.json and presets.json are never shipped: the app makes them in the user's data folder.
Source: "..\build\dist\LlamaMXD\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; The uninstaller can only read the install folder, so its progress window's logo ships with the app.
Source: "..\build\wizard\light\small-159.png"; DestDir: "{app}\uninstall"; DestName: "logo-light.png"; Flags: ignoreversion
Source: "..\build\wizard\dark\small-159.png"; DestDir: "{app}\uninstall"; DestName: "logo-dark.png"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\LlamaMXD"; Filename: "{app}\LlamaMXD.exe"; Tasks: startmenuicon
Name: "{autodesktop}\LlamaMXD"; Filename: "{app}\LlamaMXD.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\LlamaMXD.exe"; Description: "Launch LlamaMXD"; Flags: nowait postinstall skipifsilent
; An update started from inside the app (ui/updater.py) passes /RELAUNCH=1 so it comes back up.
Filename: "{app}\LlamaMXD.exe"; Flags: nowait; Check: Relaunching

[UninstallDelete]
; Folders the app itself adds to (an update leaves .old files in dependables); each is the app's own, never a shared one.
Type: filesandordirs; Name: "{app}\dependables"
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\manual"
Type: filesandordirs; Name: "{app}\licenses"
Type: filesandordirs; Name: "{app}\uninstall"

[Code]
function AppRunning: Boolean;
var
  Code: Integer;
begin
  Result := Exec(ExpandConstant('{cmd}'),
    '/C tasklist /FI "IMAGENAME eq LlamaMXD.exe" /NH | find /I "LlamaMXD.exe" > nul',
    '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
end;

{ Close every running LlamaMXD: politely first (it saves its settings), then by force. Its tools end with it. }
procedure CloseApp;
var
  Code, I: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM LlamaMXD.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  for I := 1 to 16 do
  begin
    if not AppRunning then Break;
    Sleep(500);
  end;
  if AppRunning then
    Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM LlamaMXD.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  for I := 1 to 10 do
  begin
    if not AppRunning then Break;
    Sleep(500);
  end;
  Sleep(1000);   { let Windows release the files }
end;

function InitializeUninstall: Boolean;
begin
  Result := True;
  if UninstallSilent or not AppRunning then Exit;
  Result := MsgBox('LlamaMXD is running. It has to be closed to uninstall it, and any unfinished jobs will be lost.' + #13#10#13#10 +
                   'Close it and continue?', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
end;

function Relaunching: Boolean;
begin
  Result := ExpandConstant('{param:RELAUNCH|0}') = '1';
end;

{ The uninstall progress window shows the logo like the wizard does: white line art on a dark one. }
procedure InitializeUninstallProgressForm;
var
  Name: String;
begin
  if IsDarkInstallMode then Name := 'logo-dark.png' else Name := 'logo-light.png';
  try
    UninstallProgressForm.WizardSmallBitmapImage.Stretch := True;
    UninstallProgressForm.WizardSmallBitmapImage.PngImage.LoadFromFile(ExpandConstant('{app}\uninstall\' + Name));
  except
    { Keep the default image rather than stop the uninstall. }
  end;
end;

{ Uninstalling keeps the user's settings, presets and logs unless they say otherwise. }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  { After the confirmation, before any file is removed. }
  if CurUninstallStep = usUninstall then CloseApp;
  if CurUninstallStep <> usPostUninstall then Exit;
  DataDir := ExpandConstant('{localappdata}\LlamaMXD');
  if UninstallSilent or not DirExists(DataDir) then Exit;
  if MsgBox('Also delete your LlamaMXD settings, presets and logs?' + #13#10 + DataDir,
            mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
    DelTree(DataDir, True, True, True);
end;
