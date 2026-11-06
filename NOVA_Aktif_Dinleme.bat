@echo off
cd /d "%~dp0"
echo NOVA aktif dinleme baslatiliyor...

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" nova_watcher.py
) else (
    python nova_watcher.py
)

pause
