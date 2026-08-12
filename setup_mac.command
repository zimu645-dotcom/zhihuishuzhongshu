#!/bin/bash
# 智汇中枢 - macOS 首次安装脚本
cd "$(dirname "$0")"

echo "============================================"
echo "  智汇中枢 - 智能知识工作台 (macOS 安装)"
echo "============================================"

if ! command -v python3 &> /dev/null; then
    echo "[错误] 未检测到 Python3，请先安装："
    echo "  https://www.python.org/downloads/"
    exit 1
fi

if [ ! -d "venv" ]; then
    echo "[1/3] 创建虚拟环境..."
    python3 -m venv venv || exit 1
    echo "[2/3] 安装依赖（首次约 3-5 分钟）..."
    source venv/bin/activate
    pip install -r requirements.txt || exit 1
else
    source venv/bin/activate
fi

echo "[3/3] 启动智汇中枢..."
echo "首次打开后，请到「大模型配置」页面填写你的 API 密钥。"
echo
python3 main.py
