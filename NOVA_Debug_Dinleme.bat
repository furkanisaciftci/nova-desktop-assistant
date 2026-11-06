@echo off
cd /d "%~dp0"
echo NOVA debug aktif dinleme baslatiliyor...
echo Algilanan metin ve wake durumu bu pencerede gorunecek.

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" nova_watcher.py
) else (
    python nova_watcher.py
)

pause
