@echo off
:: build.bat — One-click build script for Windows
:: Run this to produce a distributable .exe
::
:: Requirements: Python 3.10+ installed and on PATH

echo ========================================
echo  Past Paper Extractor - Build Script
echo ========================================
echo.

:: 1. Check Python
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: Python not found. Install from https://python.org
    pause
    exit /b 1
)

:: 2. Create virtual environment if needed
if not exist "venv\" (
    echo Creating virtual environment...
    python -m venv venv
)

:: 3. Activate venv
call venv\Scripts\activate.bat

:: 4. Install/upgrade dependencies
echo Installing dependencies...
pip install --upgrade pip -q
pip install -r requirements.txt -q
pip install pyinstaller -q

:: 5. Clean previous build
if exist "dist\" rmdir /s /q dist
if exist "build\" rmdir /s /q build

:: 6. Build
echo.
echo Building executable...
pyinstaller past_paper_extractor.spec --clean

:: 7. Result
if exist "dist\PastPaperExtractor.exe" (
    echo.
    echo ========================================
    echo  BUILD SUCCESSFUL!
    echo  Output: dist\PastPaperExtractor.exe
    echo  Share this single file with clients.
    echo ========================================
) else (
    echo.
    echo BUILD FAILED. Check output above for errors.
)

pause
