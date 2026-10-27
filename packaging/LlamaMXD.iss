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
; The versions of the bundled tools, so an installed tool that is newer (from an in-app update) is kept.
#ifndef ToolFfmpeg
  #error Compile through build.py --installer: it passes the bundled tools' versions.
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
Source: "..\build\dist\LlamaMXD\*"; DestDir: "{app}"; Excludes: "dependables\*"; Flags: recursesubdirs createallsubdirs ignoreversion
; The tools are copied only when missing, unreadable, or older than this installer's: a newer one that the
; in-app update installed stays. ffprobe goes with ffmpeg (they share a version).
Source: "..\build\dist\LlamaMXD\dependables\ffmpeg.exe"; DestDir: "{app}\dependables"; Flags: ignoreversion; Check: ToolNeedsCopy('ffmpeg.exe', 'ffmpeg.exe', '{#ToolFfmpeg}', '-version')
Source: "..\build\dist\LlamaMXD\dependables\ffprobe.exe"; DestDir: "{app}\dependables"; Flags: ignoreversion; Check: ToolNeedsCopy('ffprobe.exe', 'ffmpeg.exe', '{#ToolFfmpeg}', '-version')
Source: "..\build\dist\LlamaMXD\dependables\yt-dlp.exe"; DestDir: "{app}\dependables"; Flags: ignoreversion; Check: ToolNeedsCopy('yt-dlp.exe', 'yt-dlp.exe', '{#ToolYtdlp}', '--version')
Source: "..\build\dist\LlamaMXD\dependables\deno.exe"; DestDir: "{app}\dependables"; Flags: ignoreversion; Check: ToolNeedsCopy('deno.exe', 'deno.exe', '{#ToolDeno}', '--version')

[InstallDelete]
; What an in-app tool update can leave behind.
Type: files; Name: "{app}\dependables\*.old"
Type: files; Name: "{app}\dependables\*.new"
Type: files; Name: "{app}\dependables\*.part"

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

[Code]
const
  { Where Setup records an installed copy of this AppId (per-user install, so HKCU). }
  AppRegKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{21646A70-40C4-4B6B-9F66-F6F0A2B01409}_is1';

var
  InstalledVersion, InstalledDir: String;   { empty when LlamaMXD is not installed }
  ExistingPage: TInputOptionWizardPage;
  ResetBox: TNewCheckBox;
  RepairChosen, ResetChosen, LeavingToUninstall: Boolean;

{ The next whole number of a dotted version ("2026.08.19"), removed from S along with its dot. }
function TakeNumber(var S: String): Integer;
var
  I: Integer;
begin
  Result := 0;
  I := 1;
  while (I <= Length(S)) and (S[I] >= '0') and (S[I] <= '9') do
  begin
    Result := Result * 10 + StrToInt(S[I]);
    I := I + 1;
  end;
  if (I <= Length(S)) and (S[I] = '.') then I := I + 1 else I := Length(S) + 1;
  S := Copy(S, I, Length(S));
end;

{ -1, 0 or 1 as dotted version A is older than, the same as or newer than B (any "-beta" tail is ignored). }
function CompareVersions(A, B: String): Integer;
var
  NA, NB: Integer;
begin
  Result := 0;
  while (Result = 0) and ((A <> '') or (B <> '')) do
  begin
    NA := TakeNumber(A);
    NB := TakeNumber(B);
    if NA < NB then Result := -1 else if NA > NB then Result := 1;
  end;
end;

{ The version a tool reports for itself ("9.0.2", "2026.08.19"), or '' if it is missing or won't run. }
function ToolVersion(Exe, Flag: String): String;
var
  Tmp, Line, Run: String;
  Raw: AnsiString;
  Code, I: Integer;
  C: Char;
begin
  Result := '';
  if not FileExists(Exe) then Exit;
  Tmp := ExpandConstant('{tmp}\toolversion.txt');
  DeleteFile(Tmp);
  if not Exec(ExpandConstant('{cmd}'), '/C ""' + Exe + '" ' + Flag + ' > "' + Tmp + '" 2>&1"',
              '', SW_HIDE, ewWaitUntilTerminated, Code) then Exit;
  if not LoadStringFromFile(Tmp, Raw) then Exit;
  Line := String(Raw);
  I := Pos(#10, Line);
  if I > 0 then Line := Copy(Line, 1, I - 1);
  Run := '';
  for I := 1 to Length(Line) do
  begin
    C := Line[I];
    if ((C >= '0') and (C <= '9')) or ((C = '.') and (Run <> '')) then
      Run := Run + C
    else
    begin
      if Pos('.', Run) > 0 then Break;
      Run := '';
    end;
  end;
  while (Run <> '') and (Run[Length(Run)] = '.') do Delete(Run, Length(Run), 1);
  if Pos('.', Run) > 0 then Result := Run;
end;

{ Whether to copy a bundled tool over the installed one: when it is missing, won't run, or is not newer than
  this installer's (so a repair fixes a damaged one, and an in-app update to a newer tool is kept). }
function ToolNeedsCopy(Target, VersionFile, Bundled, Flag: String): Boolean;
var
  Dir, Installed: String;
begin
  Result := True;
  Dir := ExpandConstant('{app}\dependables\');
  if not FileExists(Dir + Target) then Exit;
  Installed := ToolVersion(Dir + VersionFile, Flag);
  if Installed = '' then Exit;
  Result := CompareVersions(Bundled, Installed) >= 0;
end;

{ Warn before an older installer replaces a newer LlamaMXD. }
function InitializeSetup: Boolean;
begin
  Result := True;
  InstalledVersion := '';
  InstalledDir := '';
  if not (RegQueryStringValue(HKCU, AppRegKey, 'DisplayVersion', InstalledVersion) and
          RegQueryStringValue(HKCU, AppRegKey, 'Inno Setup: App Path', InstalledDir)) then
  begin
    InstalledVersion := '';
    Exit;
  end;
  if (not WizardSilent) and (CompareVersions('{#AppVersion}', InstalledVersion) < 0) then
    Result := MsgBox('A newer LlamaMXD (' + InstalledVersion + ') is already installed. Install version {#AppVersion} over it anyway?',
                     mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
end;

procedure UpdateResetBox(Sender: TObject);
begin
  ResetBox.Enabled := ExistingPage.SelectedValueIndex = 0;
  if not ResetBox.Enabled then ResetBox.Checked := False;
end;

{ The same version already installed: offer Repair or Uninstall. A newer version is a plain upgrade. }
procedure InitializeWizard;
var
  Note: TNewStaticText;
begin
  if InstalledVersion <> '{#AppVersion}' then Exit;
  ExistingPage := CreateInputOptionPage(wpWelcome, 'LlamaMXD is already installed',
    'Version ' + InstalledVersion + ' is installed in ' + InstalledDir + '.', 'What would you like to do?', True, False);
  ExistingPage.Add('Repair LlamaMXD');
  ExistingPage.Add('Uninstall LlamaMXD');
  ExistingPage.SelectedValueIndex := 0;
  ExistingPage.CheckListBox.Height := ScaleY(54);
  Note := TNewStaticText.Create(ExistingPage);
  Note.Parent := ExistingPage.Surface;
  Note.AutoSize := False;
  Note.WordWrap := True;
  Note.Left := 0;
  Note.Top := ExistingPage.CheckListBox.Top + ExistingPage.CheckListBox.Height + ScaleY(8);
  Note.Width := ExistingPage.SurfaceWidth;
  Note.Height := ScaleY(34);
  Note.Caption := 'Repair restores any missing or damaged files. Your settings, presets and any newer tools are kept.';
  ResetBox := TNewCheckBox.Create(ExistingPage);
  ResetBox.Parent := ExistingPage.Surface;
  ResetBox.Caption := 'Reset settings to their defaults (presets and logs are kept)';
  ResetBox.Left := 0;
  ResetBox.Width := ExistingPage.SurfaceWidth;
  ResetBox.Top := Note.Top + Note.Height + ScaleY(6);
  ExistingPage.CheckListBox.OnClickCheck := @UpdateResetBox;
end;

{ A repair goes straight through: the folder, shortcuts and licence were settled by the first install. }
function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := RepairChosen and ((PageID = wpInfoBefore) or (PageID = wpSelectDir) or
                              (PageID = wpSelectTasks) or (PageID = wpReady));
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Code: Integer;
begin
  Result := True;
  if InstalledVersion <> '{#AppVersion}' then Exit;
  if CurPageID <> ExistingPage.ID then Exit;
  if ExistingPage.SelectedValueIndex = 1 then
  begin
    { Hand over to the uninstaller and close Setup. }
    LeavingToUninstall := True;
    Exec(InstalledDir + '\unins000.exe', '', '', SW_SHOWNORMAL, ewNoWait, Code);
    Result := False;
    WizardForm.Close;
  end
  else
  begin
    RepairChosen := True;
    ResetChosen := ResetBox.Checked;
  end;
end;

procedure CancelButtonClick(CurPageID: Integer; var Cancel, Confirm: Boolean);
begin
  if LeavingToUninstall then Confirm := False;
end;

{ Where the app keeps settings.json. /DATADIR=<folder> redirects it, so a test never touches the real one. }
function SettingsFolder: String;
begin
  Result := ExpandConstant('{param:DATADIR|}');
  if Result = '' then Result := ExpandConstant('{localappdata}\LlamaMXD');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  { After the files are in place (and the app, which saves on exit, has been closed). }
  if (CurStep = ssPostInstall) and ResetChosen then
    DeleteFile(SettingsFolder + '\settings.json');
end;

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

{ PowerShell that closes every process running from inside a folder (LlamaMXD's own tools included): politely
  first, then by force. It goes by the program's path, never its name, so an ffmpeg from somewhere else is left
  alone; the uninstaller's own process is skipped. }
function CloseToolsScript: String;
begin
  Result :=
    'param([string]$Dir)' + #13#10 +
    '$prefix = $Dir.TrimEnd(''\'') + ''\''' + #13#10 +
    'function Mine { Get-Process | Where-Object { $_.Path -and $_.Path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) -and $_.Name -notlike ''unins*'' } }' + #13#10 +
    'Mine | ForEach-Object { try { $null = $_.CloseMainWindow() } catch {} }' + #13#10 +
    'for ($i = 0; $i -lt 16 -and (Mine); $i++) { Start-Sleep -Milliseconds 500 }' + #13#10 +
    'Mine | Stop-Process -Force -ErrorAction SilentlyContinue' + #13#10;
end;

procedure CloseTools(Dir: String);
var
  Path: String;
  Code: Integer;
begin
  Path := ExpandConstant('{tmp}\close-tools.ps1');
  SaveStringToFile(Path, CloseToolsScript, False);
  Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
       '-NoProfile -ExecutionPolicy Bypass -File "' + Path + '" -Dir "' + Dir + '"', '', SW_HIDE, ewWaitUntilTerminated, Code);
  DeleteFile(Path);
end;

{ Every LlamaMXD, then anything else running from the install folder (a tool started by hand, say). }
procedure CloseRunningCopies(Dir: String);
begin
  CloseApp;
  CloseTools(Dir);
end;

{ Before files are replaced over an existing install: nothing may be running from it. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not DirExists(ExpandConstant('{app}')) then Exit;   { a first install has nothing to close }
  if (not WizardSilent) and AppRunning then
    if MsgBox('LlamaMXD is running. It has to be closed to install over it, and any unfinished jobs will be lost.' + #13#10#13#10 +
              'Close it and continue?', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDNO then
    begin
      Result := 'Setup was stopped because LlamaMXD is still running.';
      Exit;
    end;
  CloseRunningCopies(ExpandConstant('{app}'));
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

{ The uninstaller is not given the wizard images, so the same two logos are built into its script
  (logos.inc, generated from them) and shown on the progress window: white line art on a dark one. }
#include "..\build\wizard\logos.inc"

procedure InitializeUninstallProgressForm;
var
  Data: String;
  Size: Integer;
  Path: String;
  Stream: TFileStream;
begin
  Path := ExpandConstant('{tmp}\logo.png');
  try
    if IsDarkInstallMode then LogoDark(Data, Size) else LogoLight(Data, Size);
    Stream := TFileStream.Create(Path, fmCreate);
    try
      Stream.WriteBuffer(Data, Size);
    finally
      Stream.Free;
    end;
    { The form's own picture slot is 32px and inset; the installer's fills the 58px header, flush right. }
    with UninstallProgressForm.WizardSmallBitmapImage do
    begin
      Width := ScaleX(58);
      Height := ScaleY(58);
      Left := UninstallProgressForm.MainPanel.Width - Width;
      Top := 0;
      Stretch := True;
      PngImage.LoadFromFile(Path);
    end;
  except
    { Keep the default image rather than stop the uninstall. }
  end;
  DeleteFile(Path);
end;

{ Uninstalling keeps the user's settings, presets and logs unless they say otherwise. }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  { After the confirmation, before any file is removed. }
  if CurUninstallStep = usUninstall then CloseRunningCopies(ExpandConstant('{app}'));
  if CurUninstallStep <> usPostUninstall then Exit;
  DataDir := ExpandConstant('{localappdata}\LlamaMXD');
  if UninstallSilent or not DirExists(DataDir) then Exit;
  if MsgBox('Also delete your LlamaMXD settings, presets and logs?' + #13#10 + DataDir,
            mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
    DelTree(DataDir, True, True, True);
end;
