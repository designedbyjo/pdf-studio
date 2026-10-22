@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title PDF Studio v2.3

echo =========================================
echo PDF Studio v2.3 - Windows Launcher
echo =========================================
echo.

rem Prefer a supported Python release, NEVER default to Python 3.15.
set "PY_CMD="
py -3.12 -V >nul 2>&1
if not errorlevel 1 set "PY_CMD=py -3.12"
if not defined PY_CMD (
    py -3.13 -V >nul 2>&1
    if not errorlevel 1 set "PY_CMD=py -3.13"
)
if not defined PY_CMD (
    py -3.11 -V >nul 2>&1
    if not errorlevel 1 set "PY_CMD=py -3.11"
)
if not defined PY_CMD (
    echo [ERROR] Python 3.11, 3.12, atau 3.13 belum tersedia lewat py launcher.
    echo.
    echo Instal Python 3.12 dari:
    echo https://www.python.org/downloads/release/python-31210/
    echo.
    echo Pastikan opsi Python launcher dicentang pada installer.
    echo Setelah instalasi, tutup jendela ini dan klik file BAT lagi.
    pause
    exit /b 1
)

echo Menggunakan:
%PY_CMD% --version
echo.

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info[:2] in [(3,11),(3,12),(3,13)] else 1)" >nul 2>&1
    if errorlevel 1 (
        echo Virtual environment lama tidak kompatibel. Menghapus dan membuat ulang...
        rmdir /s /q ".venv"
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo Membuat virtual environment...
    %PY_CMD% -m venv ".venv"
    if errorlevel 1 goto :fail
)

echo Menginstal atau mengecek dependency...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :fail

echo.
echo PDF Studio berjalan di http://127.0.0.1:8000
echo Jendela ini jangan ditutup saat memakai aplikasi.
start "" /MIN cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:8000"
".venv\Scripts\python.exe" -m uvicorn server:app --host 127.0.0.1 --port 8000
if errorlevel 1 goto :fail
exit /b 0

:fail
echo.
echo [ERROR] Startup PDF Studio gagal. Baca pesan error di atas.
pause
exit /b 1
