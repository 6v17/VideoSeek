; VideoSeek — 完整包安装包（程序 + runtime\ 种子，首启自动导入）
; 由 scripts\build_release.ps1 先生成 dist\package-full\ 后再编译。
; 例: & "${env:LocalAppData}\Programs\Inno Setup 6\ISCC.exe" /DMyAppVersion=1.0.93 scripts\release\inno\VideoSeek-Full.iss

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

#define MyAppName "VideoSeek"
#define MyAppPublisher "VideoSeek"
#define MyAppURL "https://github.com/6v17/VideoSeek"
#define MyAppExeName "VideoSeek.exe"
#define PackageDir "..\..\dist\package-full"

[Setup]
AppId={{B7D3F9A2-0C5E-4A3B-9F2D-82E1C5B3D014}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion} (完整版)
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=..\..\dist
OutputBaseFilename=VideoSeek-{#MyAppVersion}-Full-Setup
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
