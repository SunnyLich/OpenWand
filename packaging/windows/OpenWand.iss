#ifndef OpenWandBundle
  #error OpenWandBundle must point to the signed PyInstaller folder.
#endif
#ifndef OpenWandVersion
  #error OpenWandVersion must match the release tag.
#endif
#ifndef OpenWandOutput
  #error OpenWandOutput must point to the installer output folder.
#endif
#ifndef OpenWandDevelopmentBuild
  #define OpenWandDevelopmentBuild 0
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
#if OpenWandDevelopmentBuild
OutputBaseFilename=OpenWand-dev-v{#OpenWandVersion}-windows-x64-setup
#else
OutputBaseFilename=OpenWand-v{#OpenWandVersion}-windows-x64-setup
#endif
Compression=lzma2
SolidCompression=yes
#if OpenWandDevelopmentBuild
SignedUninstaller=no
#else
SignedUninstaller=yes
#endif
SignedUninstallerDir={#OpenWandOutput}\signed-uninstaller
UninstallDisplayName=OpenWand
CloseApplications=yes
RestartApplications=no

[Files]
Source: "{#OpenWandBundle}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion; Excludes: "Uninstall OpenWand.bat"
Source: "{#SourcePath}\installed.marker"; DestDir: "{app}"; DestName: ".openwand-installed"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\OpenWand"; Filename: "{app}\OpenWand.exe"

[Code]
function HasUninstallOption(const Option: String): Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), Option) = 0 then
      Result := True;
end;

function ConfirmDataRemoval(var RemoveUserData: Boolean): Boolean;
var
  Dialog: TSetupForm;
  Description: TNewStaticText;
  RemoveData: TNewCheckBox;
  ContinueButton, CancelButton: TNewButton;
begin
  Dialog := CreateCustomForm(ScaleX(480), ScaleY(220), False, False);
  try
    Dialog.Caption := 'Uninstall OpenWand';
    Dialog.Position := poScreenCenter;
    Description := TNewStaticText.Create(Dialog);
    Description.Parent := Dialog;
    Description.SetBounds(ScaleX(16), ScaleY(16), ScaleX(448), ScaleY(82));
    Description.AutoSize := False;
    Description.WordWrap := True;
    Description.Caption := 'Remove OpenWand from this computer. You can also erase its settings, chats, memory, add-ons, tools, logs, downloaded packages, OpenWand-owned models, API keys, and saved OAuth sign-ins.';
    RemoveData := TNewCheckBox.Create(Dialog);
    RemoveData.Parent := Dialog;
    RemoveData.SetBounds(ScaleX(16), ScaleY(102), ScaleX(448), ScaleY(24));
    RemoveData.Caption := 'Also remove all OpenWand data and sign-ins';
    RemoveData.Checked := False;
    Description := TNewStaticText.Create(Dialog);
    Description.Parent := Dialog;
    Description.SetBounds(ScaleX(16), ScaleY(136), ScaleX(448), ScaleY(38));
    Description.AutoSize := False;
    Description.WordWrap := True;
    Description.Caption := 'External providers, their models, shared caches, browser sessions, and other apps'' sign-ins are kept.';
    ContinueButton := TNewButton.Create(Dialog);
    ContinueButton.Parent := Dialog;
    ContinueButton.SetBounds(ScaleX(280), ScaleY(184), ScaleX(88), ScaleY(24));
    ContinueButton.Caption := 'Uninstall';
    ContinueButton.ModalResult := mrOk;
    CancelButton := TNewButton.Create(Dialog);
    CancelButton.Parent := Dialog;
    CancelButton.SetBounds(ScaleX(376), ScaleY(184), ScaleX(88), ScaleY(24));
    CancelButton.Caption := 'Cancel';
    CancelButton.ModalResult := mrCancel;
    CancelButton.Cancel := True;
    CancelButton.Default := True;
    Result := Dialog.ShowModal = mrOk;
    RemoveUserData := Result and RemoveData.Checked;
  finally
    Dialog.Free;
  end;
end;

procedure InitializeUninstallProgressForm;
var
  RemoveUserData: Boolean;
  ResultCode: Integer;
begin
  { Called after the standard uninstall confirmation, before any file deletion.
    Silent uninstalls keep data unless /REMOVEUSERDATA was explicitly supplied.
    The in-app helper always uses /KEEPUSERDATA and handles its own cleanup. }
  RemoveUserData := HasUninstallOption('/REMOVEUSERDATA');
  if HasUninstallOption('/KEEPUSERDATA') then
    RemoveUserData := False
  else if not UninstallSilent and not RemoveUserData then begin
    if not ConfirmDataRemoval(RemoveUserData) then
      Abort;
  end;
  if RemoveUserData then begin
    if not Exec(ExpandConstant('{app}\OpenWand.exe'),
      '-m runtime.workers.uninstall_openwand --remove-user-data',
      ExpandConstant('{tmp}'), SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      RaiseException('Could not start saved-data cleanup. OpenWand has not been uninstalled.');
    if ResultCode = 2 then
      RaiseException('Close OpenWand before removing its saved settings and data, then run the uninstaller again.');
    if ResultCode <> 0 then
      RaiseException('Could not finish saved-data cleanup. OpenWand has not been uninstalled. See %TEMP%\openwand-uninstall-data-failures.log for details.');
  end;
end;
