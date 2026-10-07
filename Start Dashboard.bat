@echo off
REM Double-click to start the Target & Recovery dashboard and open it in the browser.
REM Keep this file next to the "dashboard" folder.
title Target and Recovery Dashboard
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0dashboard\start-dashboard.ps1"
echo.
echo The dashboard is running at http://127.0.0.1:8000
echo It keeps running in the minimised "Dashboard :8000" window. You can close this window.
ping -n 9 127.0.0.1 >nul
