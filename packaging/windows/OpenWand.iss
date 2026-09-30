#ifndef OpenWandBundle
  #error OpenWandBundle must point to the signed PyInstaller folder.
#endif
#ifndef OpenWandVersion
  #error OpenWandVersion must match the release tag.
#endif
#ifndef OpenWandOutput
  #error OpenWandOutput must point to the installer output folder.
#endif

[Setup]
AppId=OpenWand.Desktop
AppName=OpenWand
AppVersion={#OpenWandVersion}
AppPublisher=SunnyLich
AppPublisherURL=https://github.com/SunnyLich/OpenWand
AppSupportURL=https://github.com/SunnyLich/OpenWand/issues
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DefaultDirName={localappdata}\Programs\OpenWand
DefaultGroupName=OpenWand
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OpenWandOutput}
OutputBaseFilename=OpenWand-v{#OpenWandVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
SignedUninstaller=yes
SignedUninstallerDir={#OpenWandOutput}\signed-uninstaller
UninstallDisplayName=OpenWand
CloseApplications=yes
RestartApplications=no

[Files]
Source: "{#OpenWandBundle}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion; Excludes: "Uninstall OpenWand.bat"
Source: "{#SourcePath}\installed.marker"; DestDir: "{app}"; DestName: ".openwand-installed"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\OpenWand"; Filename: "{app}\OpenWand.exe"
