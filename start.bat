@echo off
rem One-click launcher for Windows. Double-click this file in Explorer.
rem Sets up a virtual environment on first run, installs dependencies,
rem starts the server on a free port, and opens the browser.
setlocal
cd /d "%~dp0"

where exiftool >nul 2>nul
if errorlevel 1 (
  echo ExifTool is required but was not found.
  echo Easiest install: open a terminal and run    winget install exiftool
  echo Or download the Windows zip from https://exiftool.org, rename
  echo "exiftool(-k).exe" to "exiftool.exe", and put it in this folder
  echo or anywhere on your PATH.
  pause
  exit /b 1
)

set PY=py -3
%PY% -c "" >nul 2>nul
if errorlevel 1 set PY=python
%PY% -c "" >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.11 or newer from
  echo https://www.python.org and tick "Add python.exe to PATH" in the
  echo installer, then run this file again.
  pause
  exit /b 1
)

if not exist .venv (
  echo First run: creating a virtual environment, takes a minute...
  %PY% -m venv .venv
  if errorlevel 1 pause & exit /b 1
)
call .venv\Scripts\activate.bat
python -m pip install -q -r requirements.txt

rem First free port at or above 8000, so another app already using 8000
rem (a different dev server, for example) is never opened by mistake.
for /f %%p in ('python -c "import socket;print(next(p for p in range(8000,8100) if socket.socket().connect_ex(('127.0.0.1',p))!=0))"') do set PORT=%%p
set URL=http://127.0.0.1:%PORT%

rem The port is known to be free, so a short delay is enough before the
rem browser opens; the server binds in well under three seconds.
start "" /min cmd /c "timeout /t 3 /nobreak >nul & start "" %URL%"

echo.
echo Metadata Inspector is starting at %URL%
echo Leave this window open while you use it. Press Ctrl+C to stop.
echo.
python -m uvicorn app.main:app --host 127.0.0.1 --port %PORT%

echo.
echo Server stopped.
pause
