@echo off
setlocal
cd /d "%~dp0"

set "CAPCAP_F5_API_HOST=127.0.0.1"
set "CAPCAP_F5_API_PORT=8766"

echo [CapCap] Starting F5 API server...
"C:\Users\Thach\AppData\Local\Programs\Python\Python311\python.exe" app\f5_api_server.py

echo.
echo [CapCap] F5 API server exited with code %ERRORLEVEL%.
pause
