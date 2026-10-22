; VideoSeek — 纯安装包（程序 only，无 runtime\ 种子）
; 由 scripts\build_release.ps1 先生成 dist\package-pure\ 后再编译。
; 例: & "${env:LocalAppData}\Programs\Inno Setup 6\ISCC.exe" /DMyAppVersion=1.0.93 scripts\release\inno\VideoSeek-Pure.iss

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

#define MyAppName "VideoSeek"
#define MyAppPublisher "VideoSeek"
#define MyAppURL "https://github.com/6v17/VideoSeek"
#define MyAppExeName "VideoSeek.exe"
#define PackageDir "..\..\dist\package-pure"

[Setup]
AppId={{A6C2E8F1-9B4D-4F2A-8E1C-71D0B4A2C903}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=
OutputDir=..\..\dist
OutputBaseFilename=VideoSeek-{#MyAppVersion}-Setup
SetupIconFile=..\..\icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#PackageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
