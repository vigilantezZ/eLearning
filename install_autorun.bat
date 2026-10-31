@echo off
title BMPTryout Auto-Run Setup
cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_autorun.ps1"
