@echo off
title BMP Tryout - Build Single File Executable (.exe)
color 0A

echo ================================================================
echo   BMP Tryout & CBT System - Compiler ke Single File .exe
echo ================================================================
echo.

echo [1/3] Memeriksa dependensi compiler PyInstaller...
python -m PyInstaller --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] PyInstaller belum terpasang. Menginstall PyInstaller...
    python -m pip install pyinstaller
) else (
    echo [V] PyInstaller siap digunakan.
)

echo.
echo [2/3] Memulai proses kompilasi BMPTryout.exe (Single File)...
echo     (Harap tunggu beberapa saat hingga proses selesai...)
echo.

python -m PyInstaller --noconfirm --clean --onefile ^
    --name "BMPTryout" ^
    --add-data "app/templates;app/templates" ^
    --add-data "app/static;app/static" ^
    --hidden-import "scipy.optimize" ^
    --hidden-import "scipy.special" ^
    --hidden-import "sklearn" ^
    --hidden-import "waitress" ^
    --hidden-import "sqlite3" ^
    --hidden-import "flask_sqlalchemy" ^
    --hidden-import "flask_login" ^
    BMPTryout.py

if %errorlevel% neq 0 (
    color 0C
    echo.
    echo ================================================================
    echo [X] GAGAL: Terjadi kesalahan saat kompilasi ke .exe!
    echo ================================================================
    goto end
)

echo.
echo ================================================================
echo [V] BERHASIL: File executable telah selesai dibuat!
echo ================================================================
echo.
echo Lokasi File .exe:
echo   %~dp0dist\BMPTryout.exe
echo.
echo Anda dapat mendistribusikan file BMPTryout.exe tersebut langsung ke customer.
echo ================================================================

:end
echo.
pause
