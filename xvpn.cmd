@echo off
setlocal
set "LAUNCHER=%LOCALAPPDATA%\xVPNManager\launch_xvpn.vbs"
if not exist "%LAUNCHER%" (
  echo xVPN Manager is not installed. Run install_windows.bat first.
  exit /b 1
)
start "" wscript.exe "%LAUNCHER%"
exit /b 0
