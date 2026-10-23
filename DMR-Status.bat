@echo off
chcp 65001 <nul >nul
title DMR Status
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\dmr-status.ps1"
echo.
pause
