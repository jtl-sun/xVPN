Option Explicit

Dim shell, fso, appPath, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

appPath = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\xVPNManager\app.py"

If Not fso.FileExists(appPath) Then
    MsgBox "xVPN Manager is not installed. Run install_windows.bat first.", 16, "xVPN Manager"
    WScript.Quit 1
End If

command = "pyw -3 """ & appPath & """"
shell.Run command, 0, False
