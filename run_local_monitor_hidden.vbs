Option Explicit

Dim shell, fileSystem, scriptDirectory, runnerPath, command, exitCode

Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")

scriptDirectory = fileSystem.GetParentFolderName(WScript.ScriptFullName)
runnerPath = fileSystem.BuildPath(scriptDirectory, "run_local_monitor.ps1")
command = "powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File """ & runnerPath & """"

exitCode = shell.Run(command, 0, True)
WScript.Quit exitCode
