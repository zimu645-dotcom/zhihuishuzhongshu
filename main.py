#!/usr/bin/env python3
"""
智汇中枢 - 智能知识工作台
入口文件
"""

import sys
import os
import signal

project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app.main_window import MainWindow
from app.config import AppConfig
from app.database import DatabaseManager
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import qInstallMessageHandler, QtMsgType


# ── 双重闪退防护 ──
# 第1层：qInstallMessageHandler 拦截 qFatal 消息
# 第2层：SIGABRT 处理器拦截 abort()（qFatal 调 abort 的必经之路）

_abort_count = 0

def sigabrt_handler(signum, frame):
    global _abort_count
    _abort_count += 1
    if _abort_count > 5:
        signal.signal(signal.SIGABRT, signal.SIG_DFL)
        return
    print(f"⚠️ [SIGABRT] 已拦截 (第{_abort_count}次)")

signal.signal(signal.SIGABRT, sigabrt_handler)

def qt_message_handler(msg_type, context, message):
    if msg_type == QtMsgType.QtFatalMsg:
        print("⚠️ [qFatal] 已拦截")
        return
    if msg_type in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg):
        if "backdrop-filter" not in message and "font family" not in message:
            print(f"Qt: {message}")

qInstallMessageHandler(qt_message_handler)


class SafeApplication(QApplication):
    def notify(self, receiver, event):
        try:
            return super().notify(receiver, event)
        except Exception:
            return False
        except BaseException:
            return False


def main():
    config = AppConfig()
    config.load()

    db = DatabaseManager(config.db_path)
    db.initialize()

    # 初始化技能系统
    from core.skill_manager import initialize as init_skills
    init_skills(config.data_dir)

    # 初始化默认模型配置：新用户首次启动预填 DeepSeek 信息，API 密钥留空由用户自己填写
    from app.database import ModelConfigDB
    with db.session() as s:
        existing = s.query(ModelConfigDB).filter(
            ModelConfigDB.model_key == "text_analysis"
        ).first()
        if not existing:
            s.add(ModelConfigDB(
                model_key="text_analysis",
                name="DeepSeek Text",
                api_key="",
                api_base="https://api.deepseek.com",
                model_name="deepseek-chat",
                enabled=True
            ))

    app = SafeApplication(sys.argv)
    app.setApplicationName("智汇中枢")
    app.setOrganizationName("智汇中枢工作室")
    app.setStyleSheet(config.get_stylesheet())

    window = MainWindow(config, db)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
