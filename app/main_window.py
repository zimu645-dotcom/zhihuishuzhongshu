"""
智汇中枢 - 主窗口
包含左侧导航栏和右侧页面切换区域
"""

import os
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QStackedWidget, QLabel, QFrame,
    QScrollArea, QSizePolicy, QApplication
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QIcon, QFont, QAction

from .config import AppConfig
from .database import DatabaseManager

from .widgets.chat_panel import ChatPanel
from .widgets.knowledge_panel import KnowledgePanel
from .widgets.analysis_panel import AnalysisPanel
from .widgets.model_config_panel import ModelConfigPanel
from .widgets.skill_panel import SkillPanel
from .widgets.recycle_panel import RecyclePanel
from .widgets.dashboard_panel import DashboardPanel


class NavButton(QPushButton):
    """导航按钮"""

    def __init__(self, text: str, icon_text: str, page_index: int, parent=None):
        super().__init__(parent)
        self.page_index = page_index
        self.setObjectName("navButton")
        self.setCheckable(True)
        self.setText(f"  {icon_text}  {text}")
        self.setMinimumHeight(48)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


class MainWindow(QMainWindow):
    """应用主窗口"""

    # 导航项定义: (显示名, 图标文字, 页面类)
    NAV_ITEMS = [
        ("会话", "💬", ChatPanel),
        ("知识库", "📚", KnowledgePanel),
        ("分析记录", "📊", AnalysisPanel),
        ("可视化大屏", "🖥️", DashboardPanel),
        ("技能", "🧩", SkillPanel),
        ("大模型配置", "⚙️", ModelConfigPanel),
    ]

    def __init__(self, config: AppConfig, db: DatabaseManager):
        super().__init__()
        self.config = config
        self.db = db
        self.nav_buttons = []
        self.current_page_index = 0

        self._init_ui()
        self._setup_menu()
        self._switch_page(0)

    def _init_ui(self):
        """初始化UI"""
        self.setWindowTitle("智汇中枢 - 智能知识工作台")
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)

        # 中心部件
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── 左侧导航栏 ──
        self._build_nav_panel(main_layout)

        # ── 右侧内容区 ──
        self._build_content_area(main_layout)

    def _build_nav_panel(self, parent_layout: QHBoxLayout):
        """构建左侧导航栏"""
        nav_panel = QWidget()
        nav_panel.setObjectName("navPanel")
        nav_panel.setFixedWidth(200)
        self._nav_collapsed = False
        self._nav_panel = nav_panel
        self._nav_width = 200

        nav_layout = QVBoxLayout(nav_panel)
        nav_layout.setContentsMargins(8, 16, 8, 8)
        nav_layout.setSpacing(4)

        # 顶部：折叠按钮 + 标题
        top_row = QHBoxLayout()
        top_row.setSpacing(0)
        self.collapse_btn = QPushButton("◀")
        self.collapse_btn.setFixedSize(30, 30)
        self.collapse_btn.setStyleSheet("""
            QPushButton {
                border: 2px solid #1a73e8; border-radius: 15px; font-size: 14px;
                background: #e8f0fe; color: #1a73e8; font-weight: bold;
            }
            QPushButton:hover { background: #1a73e8; color: white; }
        """)
        self.collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.collapse_btn.clicked.connect(self._toggle_nav)
        top_row.addWidget(self.collapse_btn)

        logo_label = QLabel("🧠 智汇中枢")
        logo_label.setStyleSheet("font-size:18px;font-weight:bold;color:#1890ff;padding:12px 12px 20px 4px")
        top_row.addWidget(logo_label)
        top_row.addStretch()
        nav_layout.addLayout(top_row)

        # 导航按钮组
        self.button_group = []
        for i, (name, icon, panel_class) in enumerate(self.NAV_ITEMS):
            btn = NavButton(name, icon, i)
            btn.clicked.connect(lambda checked, idx=i: self._switch_page(idx))
            nav_layout.addWidget(btn)
            self.button_group.append(btn)

        # 弹性空间
        nav_layout.addStretch()

        # ── 主题切换按钮 ──
        theme_frame = QFrame()
        theme_frame.setObjectName("card")
        theme_layout = QVBoxLayout(theme_frame)
        theme_layout.setContentsMargins(0, 0, 0, 0)
        self.theme_btn = QPushButton("  🌙  深色模式" if self.config.theme_mode == "light" else "  ☀️  浅色模式")
        self.theme_btn.setObjectName("navButton")
        self.theme_btn.setCheckable(False)
        self.theme_btn.clicked.connect(self._toggle_theme)
        self.theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        theme_layout.addWidget(self.theme_btn)
        nav_layout.addWidget(theme_frame)

        # 回收站按钮（底部常驻）
        recycle_frame = QFrame()
        recycle_frame.setObjectName("card")
        recycle_layout = QVBoxLayout(recycle_frame)
        recycle_layout.setContentsMargins(0, 0, 0, 0)
        recycle_btn = QPushButton("  🗑️  回收站")
        recycle_btn.setObjectName("navButton")
        recycle_btn.setCheckable(True)
        recycle_btn.clicked.connect(lambda: self._switch_recycle())
        recycle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        recycle_layout.addWidget(recycle_btn)
        self.recycle_btn = recycle_btn
        self.button_group.append(recycle_btn)

        nav_layout.addWidget(recycle_frame)

        # 版本信息
        version_label = QLabel("v0.1.0 本地版")
        version_label.setStyleSheet("color: #999; font-size: 11px; padding: 8px 12px;")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav_layout.addWidget(version_label)

        parent_layout.addWidget(nav_panel)

        self.nav_panel = nav_panel

    def _build_content_area(self, parent_layout: QHBoxLayout):
        """构建右侧内容区域"""
        # 堆叠页面
        self.stacked_widget = QStackedWidget()
        self.stacked_widget.setObjectName("contentPanel")

        # 创建各页面实例
        self.pages = {}
        for name, icon, panel_class in self.NAV_ITEMS:
            page = panel_class(self.config, self.db, self)
            self.stacked_widget.addWidget(page)
            self.pages[name] = page

        # 回收站页面（单独创建）
        self.recycle_panel = RecyclePanel(self.config, self.db, self)
        self.stacked_widget.addWidget(self.recycle_panel)
        self.recycle_index = len(self.NAV_ITEMS)

        parent_layout.addWidget(self.stacked_widget, 1)

    def _setup_menu(self):
        """设置菜单栏"""
        menu_bar = self.menuBar()

        # 文件菜单
        file_menu = menu_bar.addMenu("文件")
        import_action = QAction("导入文件...", self)
        import_action.triggered.connect(self._on_import_file)
        file_menu.addAction(import_action)

        export_action = QAction("导出...", self)
        file_menu.addAction(export_action)

        file_menu.addSeparator()
        settings_action = QAction("设置", self)
        file_menu.addAction(settings_action)

        # 帮助菜单
        help_menu = menu_bar.addMenu("帮助")
        about_action = QAction("关于智汇中枢", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _toggle_nav(self):
        """折叠/展开导航栏"""
        self._nav_collapsed = not self._nav_collapsed
        w = 50 if self._nav_collapsed else self._nav_width
        self._nav_panel.setFixedWidth(w)
        self.collapse_btn.setText("▶" if self._nav_collapsed else "◀")
        # 递归隐藏/显示所有内容，只保留折叠按钮可见
        self._set_layout_visible(self._nav_panel.layout(), not self._nav_collapsed, self.collapse_btn)

    def _set_layout_visible(self, layout, visible, keep_btn=None):
        """递归设置布局中所有部件的可见性"""
        if not layout:
            return
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if not item:
                continue
            if item.layout():
                self._set_layout_visible(item.layout(), visible, keep_btn)
            w = item.widget()
            if w and w != keep_btn:
                w.setVisible(visible)

    def _switch_page(self, index: int):
        """切换到指定页面"""
        for btn in self.button_group:
            btn.setChecked(False)
        if index < len(self.button_group):
            self.button_group[index].setChecked(True)

        self.current_page_index = index
        self.stacked_widget.setCurrentIndex(index)

        name = self.NAV_ITEMS[index][0] if index < len(self.NAV_ITEMS) else "未知"
        self.db.add_log("INFO", "system", "navigate",
                        f"切换到页面: {name}")

        widget = self.stacked_widget.currentWidget()
        if hasattr(widget, 'on_activate'):
            widget.on_activate()

    def _switch_recycle(self):
        """切换到回收站"""
        for btn in self.button_group:
            btn.setChecked(False)
        self.recycle_btn.setChecked(True)
        self.stacked_widget.setCurrentIndex(self.recycle_index)
        self.db.add_log("INFO", "system", "navigate", "切换到页面: 回收站")
        if hasattr(self.recycle_panel, 'on_activate'):
            self.recycle_panel.on_activate()

    def _on_import_file(self):
        """导入文件"""
        current_page = self.stacked_widget.currentWidget()
        if hasattr(current_page, 'on_import_file'):
            current_page.on_import_file()

    def _toggle_theme(self):
        """切换主题"""
        old_mode = self.config.theme_mode
        self.config.theme_mode = "dark" if self.config.theme_mode == "light" else "light"
        self.config.save()
        QApplication.instance().setStyleSheet(self.config.get_stylesheet())
        self.theme_btn.setText("  ☀️  浅色模式" if self.config.theme_mode == "dark" else "  🌙  深色模式")
        self.db.add_log("INFO", "system", "theme_switch",
                        f"主题切换: {old_mode} → {self.config.theme_mode}")

    def _show_about(self):
        """显示关于"""
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.about(
            self,
            "关于智汇中枢",
            "智汇中枢 v0.1.0\n\n"
            "智能知识工作台\n"
            "一款面向未来的AI知识中枢\n\n"
            "技术栈: Python + PyQt6"
        )

    def closeEvent(self, event):
        """退出时停掉本地大屏服务"""
        try:
            from core.dashboard_server import get_global_server
            get_global_server().stop()
        except Exception:
            pass
        super().closeEvent(event)
