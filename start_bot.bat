@echo off
rem Запуск Telegram-бота «Дневник привычек».
rem Логи пишутся в logs\bot.log. Запускается Планировщиком задач при входе в систему.
cd /d "%~dp0"
if not exist "logs" mkdir "logs"
set PYTHONUTF8=1
rem Логи приложения пишет сам bot.py (logs\bot.log, UTF-8).
rem Здесь ловим только фатальные ошибки до инициализации логирования.
".venv\Scripts\python.exe" bot.py 1>nul 2>> "logs\crash.log"
