@echo off
REM OpenWand debug launcher - keeps timestamped runtime logs under build_logs.
setlocal
cd /d "%~dp0"
set "OPENWAND_RUNTIME_LOG_MODE=debug"
call "Start OpenWand.bat"
