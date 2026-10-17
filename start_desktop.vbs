' Antigravity Token Dashboard - 原生静默启动器（双击完全无黑框、零闪现）
Set ws = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
currentDir = fso.GetParentFolderName(WScript.ScriptFullName)
ws.Run "pythonw """ & currentDir & "\desktop.py""", 0, False
