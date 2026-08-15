@echo off
title BMP Tryout & CBT System
color 0B

echo ================================================================
echo   Menjalankan BMP Tryout & CBT System (Local Server)
echo ================================================================
echo.

if exist "%~dp0dist\BMPTryout.exe" (
    echo Menjalankan file executable mandiri (dist\BMPTryout.exe)...
    "%~dp0dist\BMPTryout.exe"
) else (
    echo Menjalankan via Python script (BMPTryout.py)...
    python "%~dp0BMPTryout.py"
)

pause
