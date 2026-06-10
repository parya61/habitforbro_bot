' Запускает start_bot.bat в скрытом окне (без мелькающей консоли).
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
sh.Run """" & sh.CurrentDirectory & "\start_bot.bat""", 0, False
