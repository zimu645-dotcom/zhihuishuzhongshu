@echo off
chcp 65001 >nul
title ZhihuiZhongshu - Build EXE

echo ====================================
echo   ZhihuiZhongshu - Build EXE
echo ====================================
echo.

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found!
    echo Download Python 3.11 from:
    echo https://www.python.org/downloads/release/python-3119/
    echo Make sure to check "Add Python to PATH"
    pause
    exit /b
)

echo [1/3] Installing dependencies...
python -m venv venv
call venv\Scripts\activate.bat
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if %errorlevel% neq 0 (
    pause
    exit /b
)

echo [2/3] Installing PyInstaller...
pip install pyinstaller -q

echo [3/3] Building EXE (5-10 minutes, please wait)...
pyinstaller --windowed --onefile --name ZhihuiZhongshu ^
    --hidden-import=PyQt6 ^
    --hidden-import=PyQt6.QtCore ^
    --hidden-import=PyQt6.QtWidgets ^
    --hidden-import=PyQt6.QtGui ^
    --hidden-import=sqlalchemy ^
    --hidden-import=openai ^
    --collect-all PyQt6 ^
    --add-data "core;core" ^
    --add-data "app;app" ^
    --noconfirm ^
    main.py

if %errorlevel% neq 0 (
    echo [ERROR] Build failed!
    pause
    exit /b
)

echo.
echo ====================================
echo   SUCCESS!
echo   Output: dist\ZhihuiZhongshu.exe
echo   Size: ~200MB
echo.
echo  Copy ZhihuiZhongshu.exe to any
echo  Windows PC and run it directly.
echo ====================================
pause
