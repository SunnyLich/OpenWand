@echo off
setlocal
set "OPENWAND_EXE=%~1"
if "%OPENWAND_EXE%"=="" set "OPENWAND_EXE=%~dp0OpenWand.exe"

if not exist "%OPENWAND_EXE%" (
  echo OpenWand.exe was not found.
  echo.
  echo Copy this CMD and test_released_speech.ps1 beside the released OpenWand.exe,
  echo or drag OpenWand.exe onto this CMD file.
  echo.
  pause
  exit /b 2
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0test_released_speech.ps1" -OpenWandExe "%OPENWAND_EXE%" -NoPause
set "RESULT=%ERRORLEVEL%"
echo.
echo Diagnostic exit code: %RESULT%
pause
exit /b %RESULT%
