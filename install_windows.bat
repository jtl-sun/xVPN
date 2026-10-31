@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python 3 was not found. Install it from https://www.python.org/downloads/windows/
  pause
  exit /b 1
)
where pyw >nul 2>nul
if errorlevel 1 (
  echo Python windowed launcher was not found. Reinstall Python 3 with the Python Launcher option.
  pause
  exit /b 1
)
set "TARGET=%LOCALAPPDATA%\xVPNManager"
set "COMMAND_DIR=%LOCALAPPDATA%\Microsoft\WindowsApps"
if not exist "%TARGET%" mkdir "%TARGET%"
if not exist "%COMMAND_DIR%" mkdir "%COMMAND_DIR%"
xcopy /E /I /Y "%~dp0xvpn" "%TARGET%\xvpn" >nul
copy /Y "%~dp0app.py" "%TARGET%\app.py" >nul
copy /Y "%~dp0launch_xvpn.vbs" "%TARGET%\launch_xvpn.vbs" >nul
copy /Y "%~dp0xvpn.cmd" "%TARGET%\xvpn.cmd" >nul
copy /Y "%~dp0xvpn.cmd" "%COMMAND_DIR%\xvpn.cmd" >nul
copy /Y "%~dp0xvpn.cmd" "%COMMAND_DIR%\xvpn-manager.cmd" >nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "$commandDir='%COMMAND_DIR%';$userPath=[Environment]::GetEnvironmentVariable('Path','User');if ($null -eq $userPath) {$userPath=''};if (-not (($env:Path -split ';') -contains $commandDir) -and -not (($userPath -split ';') -contains $commandDir)) {[Environment]::SetEnvironmentVariable('Path',(($userPath.TrimEnd(';')+';'+$commandDir).TrimStart(';')),'User')};$w=New-Object -ComObject WScript.Shell;$s=$w.CreateShortcut([Environment]::GetFolderPath('Desktop')+'\xVPN Manager.lnk');$s.TargetPath=$env:SystemRoot+'\System32\wscript.exe';$s.Arguments=[char]34+'%TARGET%\launch_xvpn.vbs'+[char]34;$s.WorkingDirectory='%TARGET%';$s.IconLocation='%TARGET%\xvpn\assets\xvpn.ico,0';$s.Description='xVPN Manager';$s.Save()"
echo.
echo xVPN Manager was installed.
echo Use the desktop shortcut to run without a PowerShell window.
echo You can also type xvpn in an already-open PowerShell window.
echo Install official WireGuard or OpenVPN software before connecting.
where xvpn >nul 2>nul
if errorlevel 1 echo If xvpn is not found, close PowerShell, open it again, and type xvpn.
pause
