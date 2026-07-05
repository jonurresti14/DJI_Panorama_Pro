@echo off
echo ============================================================
echo   DJI Panorama Pro - Web Server
echo ============================================================
echo.
echo Starting the application...
echo Please DO NOT CLOSE this window while using the web interface.
echo.
start "" http://127.0.0.1:5000
python DJI_WebApp.py
if errorlevel 1 (
    echo.
    echo If you don't have Python installed, use the DJI_WebApp.exe executable instead!
    pause
)
