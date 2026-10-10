; Inno Setup definition for the recommended per-user MAW + MOSE Windows package.
; The build script supplies MAW_VERSION and MAW_SOURCE_DIR with /D defines.

#define AppVersion GetEnv("MAW_VERSION")
#if AppVersion == ""
  #define AppVersion "0.0.0"
#endif
#define MawSourceDir GetEnv("MAW_SOURCE_DIR")
#if MawSourceDir == ""
  #define MawSourceDir AddBackslash(SourcePath) + "..\\build\\release\\mose\\MAW"
#endif

; These are build prerequisites, never paths checked on the end user's PC.
#if !FileExists(MawSourceDir + "\MAW.exe") || !FileExists(MawSourceDir + "\MOSE\MOSE.exe")
  #error "Stage the MAW + MOSE suite before compiling the installer."
#endif
#if !FileExists(MawSourceDir + "\MOSE\resources\assets\mosp.ico") || !FileExists(MawSourceDir + "\ffmpeg\bin\ffmpeg.exe") || !FileExists(MawSourceDir + "\ffmpeg\bin\ffprobe.exe")
  #error "The suite is missing document icons or FFmpeg."
#endif

[Setup]
AppId={{4E6B4A8C-0E4F-4E88-8C9F-1DF1C9BFB0F7}
AppName=Moy's ASR Workflow
AppVersion={#AppVersion}
AppPublisher=Moyf
AppPublisherURL=https://github.com/Moyf/moys-asr-workflow
AppSupportURL=https://github.com/Moyf/moys-asr-workflow/issues
AppUpdatesURL=https://github.com/Moyf/moys-asr-workflow/releases
DefaultDirName={localappdata}\Programs\MAW
UsePreviousAppDir=yes
DefaultGroupName=Moy's ASR Workflow
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=.
OutputBaseFilename=MAW-Setup-Windows-x64-v{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupIconFile={#MawSourceDir}\_internal\assets\maw.ico
UninstallDisplayIcon={app}\_internal\assets\maw.ico
UninstallDisplayName=Moy's ASR Workflow
CloseApplications=yes
RestartApplications=yes
ChangesAssociations=yes
PrivilegesRequiredOverridesAllowed=commandline

[Files]
Source: "{#MawSourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Moy's ASR Workflow"; Filename: "{app}\MAW.exe"; WorkingDir: "{app}"
Name: "{autoprograms}\Moy's Open Subtitle Editor"; Filename: "{app}\MOSE\MOSE.exe"; WorkingDir: "{app}\MOSE"
Name: "{autodesktop}\MOSE"; Filename: "{app}\MOSE\MOSE.exe"; WorkingDir: "{app}\MOSE"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a MOSE desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\MOSE\MOSE.exe"; Description: "Open MOSE subtitle editor"; WorkingDir: "{app}\MOSE"; Flags: nowait postinstall skipifsilent; Check: not RestartMoseAfterUpdate
Filename: "{app}\MOSE\MOSE.exe"; WorkingDir: "{app}\MOSE"; Flags: nowait; Check: RestartMoseAfterUpdate

[Registry]
Root: HKCU; Subkey: "Software\Moy\MAW"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Moy\MAW"; ValueType: string; ValueName: "ExecutablePath"; ValueData: "{app}\MAW.exe"; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Moy\MAW"; ValueType: string; ValueName: "InstallKind"; ValueData: "installer"; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Moy\MAW"; ValueType: string; ValueName: "Version"; ValueData: "{#AppVersion}"; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\.mosp"; ValueType: string; ValueName: ""; ValueData: "Moy.MAW.Project"; Check: CanSetProjectDefault
Root: HKCU; Subkey: "Software\Classes\.mosp\OpenWithProgids"; ValueType: string; ValueName: "Moy.MAW.Project"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\Moy.MAW.Project"; ValueType: string; ValueName: ""; ValueData: "MAW Project"; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\Moy.MAW.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\MOSE\resources\assets\mosp.ico"",0"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Moy.MAW.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\MOSE\MOSE.exe"" ""%1"""; Flags: uninsdeletekeyifempty

[Code]
function RestartMoseAfterUpdate(): Boolean;
begin
  Result := ExpandConstant('{param:MOSEUPDATE|0}') = '1';
end;

function CanSetProjectDefault(): Boolean;
var Handler: String;
begin
  Result := not RegKeyExists(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.mosp\UserChoice') and
    (not RegQueryStringValue(HKCR, '.mosp', '', Handler) or (Handler = '') or (Handler = 'Moy.MAW.Project'));
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var Handler: String;
begin
  if (CurUninstallStep = usUninstall) and RegQueryStringValue(HKCU, 'Software\Classes\.mosp', '', Handler) and
    (Handler = 'Moy.MAW.Project') then
    RegDeleteValue(HKCU, 'Software\Classes\.mosp', '');
end;
