Option Explicit

Dim shell, fso, root, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

root = fso.GetParentFolderName(WScript.ScriptFullName)
command = """" & root & "\start_djua_gateway.bat" & """"

shell.Run command, 0, False
