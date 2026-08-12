@echo off
setlocal
cd /d "%~dp0"

rem This launcher intentionally delegates all validation and removal to OpenWand's
rem shared uninstaller. It must not contain its own deletion commands.
if exist "%~dp0OpenWand.exe" (
    start "" "%~dp0OpenWand.exe" -m runtime.workers.uninstall_openwand
    exit /b 0
)

if exist "%~dp0.venv\Scripts\pythonw.exe" (
    start "" "%~dp0.venv\Scripts\pythonw.exe" -m runtime.workers.uninstall_openwand
    exit /b 0
)

if exist "%~dp0.venv-build\Scripts\pythonw.exe" (
    start "" "%~dp0.venv-build\Scripts\pythonw.exe" -m runtime.workers.uninstall_openwand
    exit /b 0
)

echo ERROR: OpenWand.exe or a OpenWand Python environment was not found beside this file.
echo Keep Uninstall OpenWand.bat in the OpenWand folder, then try again.
pause
exit /b 1
