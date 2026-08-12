"""
智汇中枢 - 配置管理模块
"""

import os
import sys
import json
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class ModelConfig:
    """单个大模型配置"""
    name: str = ""
    api_key: str = ""
    api_base: str = ""
    model_name: str = ""
    enabled: bool = False
    connect_timeout: int = 30
    max_retries: int = 3

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**data)


@dataclass
class AppConfig:
    """应用全局配置"""

    # 路径
    app_dir: str = ""
    db_path: str = ""
    data_dir: str = ""
    log_dir: str = ""
    upload_dir: str = ""
    export_dir: str = ""
    static_dir: str = ""

    # 文件限制
    max_file_size: int = 50 * 1024 * 1024  # 50MB
    supported_formats: list = field(default_factory=lambda: [
        ".txt", ".md", ".pdf", ".docx", ".xlsx", ".pptx",
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp",
        ".csv", ".json", ".yaml", ".yml", ".xml", ".html"
    ])

    # 向量化
    chunk_size: int = 512
    chunk_overlap: int = 64
    embedding_model: str = "BAAI/bge-small-zh-v1.5"

    # 会话
    max_context_messages: int = 50
    context_compress_threshold: int = 4000

    # 日志
    log_level: str = "DEBUG"
    log_retention_days: int = 30

    # 回收站
    recycle_retention_days: int = 30

    # 模型配置（默认预置 DeepSeek API，密钥留空由用户填写）
    models: dict = field(default_factory=lambda: {
        "text_analysis": ModelConfig(
            name="DeepSeek Text",
            api_key="",
            api_base="https://api.deepseek.com",
            model_name="deepseek-chat",
            enabled=True
        ),
        "vision": ModelConfig(
            name="GPT Vision",
            api_base="https://api.openai.com/v1",
            model_name="gpt-4o"
        ),
    })

    # 界面主题
    theme_mode: str = "light"  # light | dark

    def __post_init__(self):
        if not self.app_dir:
            self.app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if not self.data_dir:
            # 打包后使用固定路径，不依赖 app 位置
            if getattr(sys, 'frozen', False):
                # PyInstaller 打包模式
                home = os.path.expanduser("~")
                self.data_dir = os.path.join(home, ".zhihuishuniu", "data")
            else:
                self.data_dir = os.path.join(self.app_dir, "data")
        if not self.db_path:
            self.db_path = os.path.join(self.data_dir, "zhihuishuniu.db")
        if not self.db_path:
            self.db_path = os.path.join(self.data_dir, "zhihuishuniu.db")
        if not self.log_dir:
            self.log_dir = os.path.join(self.data_dir, "logs")
        if not self.upload_dir:
            self.upload_dir = os.path.join(self.data_dir, "uploads")
        if not self.export_dir:
            self.export_dir = os.path.join(self.data_dir, "exports")
        if not self.static_dir:
            self.static_dir = os.path.join(self.data_dir, "static")

        self._ensure_dirs()

    def _ensure_dirs(self):
        """确保所有目录存在"""
        for d in [self.data_dir, self.log_dir, self.upload_dir, self.export_dir, self.static_dir]:
            os.makedirs(d, exist_ok=True)

    # ─── 配置文件读写 ───

    CONFIG_FILE = "config.json"

    @property
    def config_path(self) -> str:
        return os.path.join(self.data_dir, self.CONFIG_FILE)

    def save(self):
        """保存配置到文件"""
        data = {
            "max_file_size": self.max_file_size,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "embedding_model": self.embedding_model,
            "max_context_messages": self.max_context_messages,
            "log_level": self.log_level,
            "recycle_retention_days": self.recycle_retention_days,
            "theme_mode": self.theme_mode,
            "models": {
                k: v.to_dict() for k, v in self.models.items()
            }
        }
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self):
        """从文件加载配置"""
        if not os.path.exists(self.config_path):
            return
        with open(self.config_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.max_file_size = data.get("max_file_size", self.max_file_size)
        self.chunk_size = data.get("chunk_size", self.chunk_size)
        self.chunk_overlap = data.get("chunk_overlap", self.chunk_overlap)
        self.embedding_model = data.get("embedding_model", self.embedding_model)
        self.max_context_messages = data.get("max_context_messages", self.max_context_messages)
        self.log_level = data.get("log_level", self.log_level)
        self.recycle_retention_days = data.get("recycle_retention_days", self.recycle_retention_days)
        self.theme_mode = data.get("theme_mode", self.theme_mode)

        models_data = data.get("models", {})
        for key, val in models_data.items():
            if key in self.models:
                self.models[key] = ModelConfig.from_dict(val)

    # ─── 界面样式 ───

    def get_stylesheet(self) -> str:
        """获取全局样式表"""
        if self.theme_mode == "dark":
            return self._dark_theme()
        return self._light_theme()

    def _light_theme(self) -> str:
        return """
        /* ═══════════════════════════════════════════
           智汇中枢 - 科技感主题 v3 (极简精致)
           ═══════════════════════════════════════════ */

        * {
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "Inter", "Microsoft YaHei", sans-serif;
            font-size: 13px;
        }
        QMainWindow { background: #f2f3f7; }

        /* ── 左侧导航 ── */
        QWidget#navPanel {
            background: rgba(255,255,255,0.95);
        }
        QPushButton#navButton {
            text-align: left; padding: 10px 16px; margin: 1px 6px;
            border: none; border-radius: 8px;
            color: #5f6368; font-size: 13px; background: transparent;
            font-weight: 450;
        }
        QPushButton#navButton:hover { background: rgba(60,130,250,0.07); color: #1a73e8; }
        QPushButton#navButton:checked {
            background: rgba(60,130,250,0.1); color: #1a73e8; font-weight: 550;
            border-left: 2.5px solid #1a73e8;
        }

        /* ── 内容面板 ── */
        QWidget#contentPanel { background: #f2f3f7; }

        /* ── 卡片 ── */
        QFrame#card {
            background: #ffffff;
            border: 1px solid rgba(0,0,0,0.04);
            border-radius: 12px;
        }

        /* ── 通用按钮 ── */
        QPushButton {
            border: 1px solid rgba(0,0,0,0.08); border-radius: 7px;
            padding: 6px 16px; background: #ffffff; color: #3c4043;
            font-weight: 450;
        }
        QPushButton:hover { border-color: #1a73e8; color: #1a73e8; background: #f8fbff; }
        QPushButton:pressed { background: #eef3fc; }
        QPushButton:disabled { opacity: 0.4; }
        QPushButton#primaryButton {
            background: #1a73e8; color: white; border: none;
            font-weight: 500; border-radius: 7px; padding: 7px 20px;
        }
        QPushButton#primaryButton:hover { background: #1765cc; }
        QPushButton#primaryButton:disabled { background: #c4c7cc; }

        /* ── 危险按钮 ── */
        QPushButton#dangerButton { background: #ea4335; color: white; border: none; border-radius: 7px; }
        QPushButton#dangerButton:hover { background: #d33828; }

        /* ── 输入框 ── */
        QLineEdit, QTextEdit, QPlainTextEdit {
            border: 1px solid rgba(0,0,0,0.08); border-radius: 9px;
            padding: 8px 12px; background: #ffffff; color: #202124;
            selection-background-color: #cfe2ff;
        }
        QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
            border-color: #1a73e8; background: #ffffff;
        }

        /* ── 下拉框 ── */
        QComboBox {
            border: 1px solid rgba(0,0,0,0.08); border-radius: 7px;
            padding: 5px 10px; background: #ffffff; color: #3c4043;
        }
        QComboBox:hover { border-color: #1a73e8; }
        QComboBox::drop-down { border: none; width: 26px; }
        QComboBox::down-arrow { width: 10px; height: 10px; }
        QComboBox QAbstractItemView {
            border: 1px solid #e0e0e0; border-radius: 8px; background: #ffffff; padding: 4px;
            selection-background-color: #e8f0fe; selection-color: #1a73e8;
        }

        /* ── 标题 ── */
        QLabel#sectionTitle {
            font-size: 20px; font-weight: 600; color: #202124;
            letter-spacing: -0.3px;
        }

        /* ── 滚动条 ── */
        QScrollBar:vertical {
            border: none; background: transparent; width: 5px;
        }
        QScrollBar::handle:vertical {
            background: rgba(0,0,0,0.12); border-radius: 3px; min-height: 30px;
        }
        QScrollBar::handle:vertical:hover { background: rgba(0,0,0,0.2); }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

        /* ── 表格 ── */
        QTableWidget {
            border: 1px solid rgba(0,0,0,0.06); border-radius: 10px;
            background: #ffffff; gridline-color: rgba(0,0,0,0.04);
        }
        QTableWidget::item { padding: 7px 10px; color: #3c4043; }
        QTableWidget::item:selected { background: #e8f0fe; color: #1a73e8; }
        QHeaderView::section {
            background: #fafafa; border: none;
            border-bottom: 1px solid rgba(0,0,0,0.06); padding: 9px 10px;
            font-weight: 500; color: #5f6368; font-size: 12px;
        }

        /* ── 树形控件 ── */
        QTreeWidget { border: none; background: transparent; }
        QTreeWidget::item { padding: 5px 4px; border-radius: 5px; color: #3c4043; }
        QTreeWidget::item:hover { background: rgba(60,130,250,0.06); }
        QTreeWidget::item:selected { background: rgba(60,130,250,0.1); color: #1a73e8; }

        /* ── 列表 ── */
        QListWidget { border: none; background: transparent; }
        QListWidget::item { border-radius: 7px; color: #3c4043; }
        QListWidget::item:hover { background: rgba(0,0,0,0.03); }
        QListWidget::item:selected { background: rgba(60,130,250,0.1); }

        /* ── 菜单 ── */
        QMenu {
            border: 1px solid rgba(0,0,0,0.06); border-radius: 10px;
            background: rgba(255,255,255,0.98); padding: 5px;
        }
        QMenu::item { padding: 7px 22px; border-radius: 5px; font-size: 13px; color: #3c4043; }
        QMenu::item:selected { background: #e8f0fe; color: #1a73e8; }
        QMenu::separator { margin: 4px 8px; height: 1px; background: rgba(0,0,0,0.06); }

        /* ── 弹窗 ── */
        QMessageBox { background: #ffffff; border-radius: 12px; }
        QMessageBox QLabel { font-size: 13px; color: #3c4043; }

        /* ── 分组框 ── */
        QGroupBox {
            border: 1px solid rgba(0,0,0,0.06); border-radius: 10px;
            margin-top: 14px; padding: 16px 12px; color: #3c4043;
        }
        QGroupBox::title {
            subcontrol-origin: margin; subcontrol-position: top left;
            padding: 0 8px; color: #5f6368;
        }

        /* ── 标签页 ── */
        QTabWidget::pane { border: 1px solid rgba(0,0,0,0.06); border-radius: 10px; background: transparent; }
        QTabBar::tab {
            padding: 9px 22px; border: none; color: #5f6368;
            font-weight: 450; font-size: 13px;
        }
        QTabBar::tab:selected { color: #1a73e8; border-bottom: 2px solid #1a73e8; }
        QTabBar::tab:hover { color: #202124; }
        """

    def _dark_theme(self) -> str:
        return """
        * { font-family: -apple-system,"Microsoft YaHei","PingFang SC","Noto Sans SC",sans-serif; font-size: 13px; }
        QMainWindow { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0#0d1117,stop:1#161b22); }
        QWidget#navPanel { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0#161b22,stop:1#0d1117); border-right:1px solid #21262d; }
        QPushButton#navButton { text-align:left; padding:12px 18px; margin:2px 8px; border:none; border-radius:10px; color:#8b949e; font-size:14px; background:transparent; }
        QPushButton#navButton:hover { background:rgba(88,166,255,0.1); color:#58a6ff; }
        QPushButton#navButton:checked { background:rgba(88,166,255,0.15); color:#58a6ff; font-weight:600; border-left:3px solid #58a6ff; }
        QWidget#contentPanel { background:#0d1117; }
        QFrame#card { background:#161b22; border:1px solid #21262d; border-radius:12px; }
        QPushButton { border:1px solid #30363d; border-radius:8px; padding:7px 18px; background:#21262d; color:#c9d1d9; }
        QPushButton:hover { border-color:#58a6ff; color:#58a6ff; }
        QPushButton#primaryButton { background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0#238636,stop:1#196c2e); color:white; border:none; font-weight:600; border-radius:8px; }
        QPushButton#primaryButton:hover { background:#2ea043; }
        QPushButton#primaryButton:disabled { background:#21262d; color:#484f58; }
        QPushButton#dangerButton { background:#da3633; color:white; border:none; border-radius:8px; }
        QLineEdit,QTextEdit,QPlainTextEdit { border:1px solid #30363d; border-radius:10px; padding:9px 14px; background:#0d1117; color:#c9d1d9; selection-background-color:#58a6ff; }
        QLineEdit:focus,QTextEdit:focus,QPlainTextEdit:focus { border-color:#58a6ff; }
        QComboBox { border:1px solid #30363d; border-radius:8px; padding:6px 12px; background:#21262d; color:#c9d1d9; }
        QComboBox:hover { border-color:#58a6ff; }
        QComboBox QAbstractItemView { border:1px solid #30363d; border-radius:8px; background:#161b22; selection-background-color:#1f3a5f; selection-color:#58a6ff; }
        QLabel#sectionTitle { font-size:22px; font-weight:700; color:#e6edf3; }
        QScrollBar:vertical { border:none; background:transparent; width:6px; }
        QScrollBar::handle:vertical { background:rgba(255,255,255,0.12); border-radius:3px; min-height:30px; }
        QScrollBar::handle:vertical:hover { background:rgba(255,255,255,0.25); }
        QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height:0; }
        QTableWidget { border:1px solid #30363d; border-radius:10px; background:#161b22; gridline-color:#21262d; color:#c9d1d9; }
        QTableWidget::item:selected { background:#1f3a5f; color:#58a6ff; }
        QHeaderView::section { background:#0d1117; border:none; border-bottom:1px solid #30363d; padding:10px; font-weight:600; color:#8b949e; }
        QTreeWidget { border:none; background:transparent; color:#c9d1d9; }
        QTreeWidget::item { padding:6px 4px; border-radius:6px; }
        QTreeWidget::item:hover { background:rgba(88,166,255,0.08); }
        QTreeWidget::item:selected { background:rgba(88,166,255,0.15); color:#58a6ff; }
        QListWidget { border:none; background:transparent; color:#c9d1d9; }
        QListWidget::item { border-radius:8px; }
        QListWidget::item:hover { background:rgba(255,255,255,0.05); }
        QListWidget::item:selected { background:rgba(88,166,255,0.15); }
        QMenu { border:1px solid #30363d; border-radius:10px; background:#161b22; padding:6px; color:#c9d1d9; }
        QMenu::item { padding:8px 24px; border-radius:6px; }
        QMenu::item:selected { background:#1f3a5f; color:#58a6ff; }
        QMessageBox { background:#161b22; color:#c9d1d9; }
        QGroupBox { border:1px solid #30363d; border-radius:10px; margin-top:16px; padding:16px 12px; color:#c9d1d9; }
        QGroupBox::title { subcontrol-origin:margin; subcontrol-position:top left; padding:0 8px; color:#8b949e; }
        QTabWidget::pane { border:1px solid #30363d; border-radius:10px; }
        QTabBar::tab { padding:10px 24px; border:none; color:#8b949e; }
        QTabBar::tab:selected { color:#58a6ff; border-bottom:2px solid #58a6ff; }
        """
