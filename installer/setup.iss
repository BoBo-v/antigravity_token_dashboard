; Inno Setup 6 脚本配置 - Antigravity Token Dashboard 安装包向导
; 使用开源免费的 Inno Setup (https://jrsoftware.org/isdl.php) 编译为 Setup.exe
#define MyAppName "Antigravity Token Dashboard"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Antigravity Community"
#define MyAppURL "https://github.com/BoBo-v/antigravity_token_dashboard"
#define MyAppExeName "AntigravityDashboard.exe"

[Setup]
AppId={{9F82C431-7C4E-4B52-9D86-8A30B1C47021}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist_installer
OutputBaseFilename=Antigravity_Token_Dashboard_Setup_v{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; 打包后的独立主程序
Source: "..\dist\AntigravityDashboard.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
