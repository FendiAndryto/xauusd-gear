@echo off
REM XAUUSD SMC Assistant - visible debug launcher (ticket T-10)
REM Pakai Start_Assistant.vbs untuk pemakaian harian (tanpa jendela hitam).
setlocal
cd /d "%~dp0"
set "PYTHON=%~dp0.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
  echo [ERROR] Environment Python tidak ditemukan: "%PYTHON%"
  echo         Sekali saja: uv sync --python 3.12
  pause
  exit /b 1
)
if not exist "%~dp0logs" mkdir "%~dp0logs"

"%PYTHON%" -c "import fastapi, uvicorn" >nul 2>&1
if errorlevel 1 (
  echo [SETUP] Memasang dependency web, sekali saja...
  uv pip install --python "%PYTHON%" "fastapi>=0.110.0" "uvicorn[standard]>=0.29.0"
  if errorlevel 1 (
    "%PYTHON%" -m ensurepip --upgrade >nul 2>&1
    "%PYTHON%" -m pip install --quiet --disable-pip-version-check "fastapi>=0.110.0" "uvicorn[standard]>=0.29.0"
  )
)

echo.
echo  XAUUSD Assistant  -  http://localhost:8000
echo  Tutup jendela ini untuk menghentikan server.
echo.
start "" /min cmd /c "timeout /t 3 >nul && explorer http://localhost:8000"
"%PYTHON%" -m uvicorn src.assistant.app:app --host 127.0.0.1 --port 8000
pause
