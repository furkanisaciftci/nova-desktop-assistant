@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "nova_watcher.py"
) else (
    start "" pythonw "nova_watcher.py"
)
