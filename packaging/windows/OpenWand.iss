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
; Native order: welcome confirmation, language selection, then the wizard.
DisableStartupPrompt=no
ShowLanguageDialog=yes
UsePreviousLanguage=yes
DisableWelcomePage=yes
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

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "zhHant"; MessagesFile: "{#SourcePath}\languages\ChineseTraditional.isl"
Name: "zh"; MessagesFile: "{#SourcePath}\languages\ChineseSimplified.isl"
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"

#include "InstallerMessages.iss"

[Files]
Source: "{#OpenWandBundle}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion; Excludes: "Uninstall OpenWand.bat"
Source: "{#SourcePath}\installed.marker"; DestDir: "{app}"; DestName: ".openwand-installed"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\OpenWand"; Filename: "{app}\OpenWand.exe"

[Code]
const
  OpenWandUninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\OpenWand.Desktop_is1';

var
  ExistingInstall: Boolean;
  ExistingVersion, ExistingDirectory, ExistingUninstaller: String;
  VersionKnown, CanInstall, MaintenanceFinished: Boolean;
  VersionComparison, InstallChoice, UninstallChoice: Integer;
  MaintenancePage: TInputOptionWizardPage;

procedure ShowInstallerMessage(const Text: String; const Kind: TMsgBoxType);
begin
  TaskDialogMsgBox('', Text, Kind, MB_OK, [SetupMessage(msgButtonOK)], 0);
end;

function ReadExistingInstall(const RootKey: Integer): Boolean;
begin
  Result := RegQueryStringValue(RootKey, OpenWandUninstallKey,
    'InstallLocation', ExistingDirectory);
  if Result then begin
    ExistingDirectory := RemoveBackslashUnlessRoot(ExistingDirectory);
    Result := ExistingDirectory <> '';
  end;
  if Result then begin
    RegQueryStringValue(RootKey, OpenWandUninstallKey, 'DisplayVersion', ExistingVersion);
    RegQueryStringValue(RootKey, OpenWandUninstallKey, 'UninstallString', ExistingUninstaller);
    ExistingUninstaller := RemoveQuotes(ExistingUninstaller);
    { Only offer the registered uninstaller from this installation directory. }
    if (CompareText(ExtractFileDir(ExistingUninstaller), ExistingDirectory) <> 0) or
       not FileExists(ExistingUninstaller) then
      ExistingUninstaller := '';
  end;
end;

function InitializeSetup: Boolean;
var
  Installed, Bundled: Int64;
  Warning: String;
begin
  ExistingInstall := ReadExistingInstall(HKCU64);
  if not ExistingInstall then
    ExistingInstall := ReadExistingInstall(HKCU32);
  CanInstall := True;
  Result := True;
  if ExistingInstall then begin
    VersionKnown := StrToVersion(ExistingVersion, Installed) and
      StrToVersion('{#OpenWandVersion}', Bundled);
    CanInstall := False;
    if VersionKnown then begin
      VersionComparison := ComparePackedVersion(Bundled, Installed);
      CanInstall := True;
    end;
    Log(Format('Existing OpenWand: version=%s; directory=%s', [ExistingVersion, ExistingDirectory]));
    if VersionKnown and (VersionComparison < 0) then begin
      Warning := Format('Version downgrade: OpenWand %s is already installed, but this installer contains %s.', [ExistingVersion, '{#OpenWandVersion}']);
      Log(Warning);
      if not WizardSilent then
        { InitializeSetup runs after Inno's native language selection dialog. }
        Result := TaskDialogMsgBox(CustomMessage('DowngradeTitle'),
          FmtMessage(CustomMessage('DowngradeNotice'), [ExistingVersion, '{#OpenWandVersion}']),
          mbConfirmation, MB_YESNO, [CustomMessage('ContinueDowngrade'), CustomMessage('Cancel')], 0) = IDYES;
    end else if not CanInstall then begin
      Warning := 'The installed OpenWand version could not be recognized. Setup will not overwrite it.';
      Log(Warning);
      if WizardSilent then
        Result := False
      else
        ShowInstallerMessage(CustomMessage('UnknownVersion') + #13#10#13#10 + CustomMessage('UnknownHelp'), mbError);
    end;
  end;
end;

procedure InitializeWizard;
var
  Description, Action: String;
begin
  if not ExistingInstall then
    Exit;
  if ExpandConstant('{param:DIR|}') = '' then
    WizardForm.DirEdit.Text := ExistingDirectory;
  Description := FmtMessage(CustomMessage('Versions'), [ExistingVersion, '{#OpenWandVersion}']);
  if CanInstall and (VersionComparison < 0) then
    Action := CustomMessage('DowngradeActions')
  else if CanInstall then
    Action := CustomMessage('Actions')
  else
    Action := CustomMessage('UnknownActions');
  MaintenancePage := CreateInputOptionPage(wpWelcome, CustomMessage('ManageTitle'),
    Description, Action + #13#10#13#10 + FmtMessage(CustomMessage('Location'), [ExistingDirectory]),
    True, False);
  InstallChoice := -1;
  UninstallChoice := -1;
  if CanInstall then begin
    if VersionComparison > 0 then
      InstallChoice := MaintenancePage.Add(FmtMessage(CustomMessage('Update'), ['{#OpenWandVersion}']))
    else if VersionComparison < 0 then
      InstallChoice := MaintenancePage.Add(FmtMessage(CustomMessage('Downgrade'), ['{#OpenWandVersion}']))
    else
      InstallChoice := MaintenancePage.Add(FmtMessage(CustomMessage('Repair'), ['{#OpenWandVersion}']));
  end;
  if ExistingUninstaller <> '' then
    UninstallChoice := MaintenancePage.Add(CustomMessage('UninstallAction'));
  { Do not select Uninstall automatically when the version is unrecognized. }
  MaintenancePage.SelectedValueIndex := InstallChoice;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := ExistingInstall and (PageID = wpSelectDir);
  if ExistingInstall and (MaintenancePage <> nil) then
    if PageID = MaintenancePage.ID then
      Result := WizardSilent;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  ResultCode: Integer;
begin
  Result := True;
  if MaintenancePage = nil then
    Exit;
  if CurPageID <> MaintenancePage.ID then
    Exit;
  if (UninstallChoice >= 0) and
     (MaintenancePage.SelectedValueIndex = UninstallChoice) then begin
    Result := False;
    if not Exec(ExistingUninstaller, '/NORESTART', ExistingDirectory,
      SW_SHOWNORMAL, ewWaitUntilTerminated, ResultCode) then begin
      ShowInstallerMessage(CustomMessage('UninstallStartError'), mbError);
      Exit;
    end;
    if not RegKeyExists(HKCU64, OpenWandUninstallKey) and
       not RegKeyExists(HKCU32, OpenWandUninstallKey) then begin
      MaintenanceFinished := True;
      WizardForm.Close;
    end else if ResultCode <> 0 then
      Log(Format('Uninstall cancelled or failed (exit %d); keeping Setup on the maintenance page.', [ResultCode]));
  end else if not CanInstall or (MaintenancePage.SelectedValueIndex <> InstallChoice) then begin
    ShowInstallerMessage(CustomMessage('SelectAction'), mbInformation);
    Result := False;
  end;
end;

procedure CancelButtonClick(CurPageID: Integer; var Cancel, Confirm: Boolean);
begin
  if MaintenanceFinished then
    Confirm := False;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if ExistingInstall then begin
    if not CanInstall then
      Result := CustomMessage('UnknownVersion')
    else if CompareText(RemoveBackslashUnlessRoot(ExpandFileName(WizardDirValue)),
      RemoveBackslashUnlessRoot(ExpandFileName(ExistingDirectory))) <> 0 then
      Result := CustomMessage('SameDirectory');
  end;
end;

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
  Dialog := CreateCustomForm(ScaleX(560), ScaleY(310), False, False);
  try
    Dialog.Caption := CustomMessage('UninstallTitle');
    Dialog.Position := poScreenCenter;
    Description := TNewStaticText.Create(Dialog);
    Description.Parent := Dialog;
    Description.SetBounds(ScaleX(16), ScaleY(16), ScaleX(528), ScaleY(124));
    Description.AutoSize := False;
    Description.WordWrap := True;
    Description.Caption := CustomMessage('RemoveDescription');
    RemoveData := TNewCheckBox.Create(Dialog);
    RemoveData.Parent := Dialog;
    RemoveData.SetBounds(ScaleX(16), ScaleY(150), ScaleX(528), ScaleY(24));
    RemoveData.Caption := CustomMessage('RemoveData');
    RemoveData.Checked := False;
    Description := TNewStaticText.Create(Dialog);
    Description.Parent := Dialog;
    Description.SetBounds(ScaleX(16), ScaleY(188), ScaleX(528), ScaleY(64));
    Description.AutoSize := False;
    Description.WordWrap := True;
    Description.Caption := CustomMessage('ExternalKept');
    ContinueButton := TNewButton.Create(Dialog);
    ContinueButton.Parent := Dialog;
    ContinueButton.SetBounds(ScaleX(314), ScaleY(270), ScaleX(110), ScaleY(24));
    ContinueButton.Caption := CustomMessage('Uninstall');
    ContinueButton.ModalResult := mrOk;
    CancelButton := TNewButton.Create(Dialog);
    CancelButton.Parent := Dialog;
    CancelButton.SetBounds(ScaleX(434), ScaleY(270), ScaleX(110), ScaleY(24));
    CancelButton.Caption := CustomMessage('Cancel');
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
      RaiseException(CustomMessage('CleanupStartError'));
    if ResultCode = 2 then
      RaiseException(CustomMessage('CloseBeforeCleanup'));
    if ResultCode <> 0 then
      RaiseException(CustomMessage('CleanupFailed'));
  end;
end;
