@echo off
chcp 65001 >nul
title 智汇中枢 - 智能知识工作台
cd /d "%~dp0"

echo ============================================
echo   智汇中枢 - 智能知识工作台
echo ============================================
echo.

:: 检查 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python！
    echo 请先安装 Python 3.10~3.12，安装时勾选 "Add Python to PATH"：
    echo https://www.python.org/downloads/
    pause
    exit /b
)

:: 首次运行创建虚拟环境并安装依赖
if not exist "venv" (
    echo [1/3] 首次运行，正在创建虚拟环境...
    python -m venv venv
    if %errorlevel% neq 0 ( pause & exit /b )
    echo [2/3] 正在安装依赖（首次约 3-5 分钟）...
    call venv\Scripts\activate.bat
    pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    if %errorlevel% neq 0 ( pause & exit /b )
) else (
    call venv\Scripts\activate.bat
)

echo [3/3] 启动智汇中枢...
echo 首次打开后，请到「大模型配置」页面填写你的 API 密钥。
echo.
python main.py
pause
