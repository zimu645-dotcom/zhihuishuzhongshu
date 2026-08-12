"""
智汇中枢 - 可视化大屏管理面板
列出所有生成的大屏，可重新打开、查看历史版本
"""

import json
import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QMenu, QMessageBox
)
from PyQt6.QtCore import Qt


class DashboardPanel(QWidget):
    """可视化大屏管理面板"""

    def __init__(self, config, db, main_window):
        super().__init__()
        self.config = config
        self.db = db
        self.main_window = main_window
        self._rows = []
        self._init_ui()
        self._load_data()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        top_layout = QHBoxLayout()
        title = QLabel("🖥️ 可视化大屏")
        title.setObjectName("sectionTitle")
        top_layout.addWidget(title)
        top_layout.addStretch()
        self.refresh_btn = QPushButton("  🔄  刷新")
        self.refresh_btn.clicked.connect(self._load_data)
        top_layout.addWidget(self.refresh_btn)
        layout.addLayout(top_layout)

        hint = QLabel("双击记录可在浏览器中重新打开大屏；右键查看历史版本。"
                      "在「会话」页对大屏说“调整/优化/改成浅色”即可生成新版本。")
        hint.setStyleSheet("color: #888; font-size: 13px; padding: 0 0 8px 0;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["标题", "版本", "文件数", "生成时间", "文件路径", "链接"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 70)
        self.table.setColumnWidth(2, 70)
        self.table.setColumnWidth(3, 150)
        self.table.setColumnWidth(4, 260)
        self.table.setColumnWidth(5, 220)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        self.table.itemDoubleClicked.connect(self._on_open_item)
        layout.addWidget(self.table, 1)

    def _load_data(self):
        self.table.setRowCount(0)
        try:
            from app.database import Dashboard
            with self.db.session() as s:
                rows = s.query(Dashboard).order_by(
                    Dashboard.updated_at.desc()).limit(200).all()
        except Exception:
            rows = []
        self._rows = rows
        self.table.setRowCount(len(rows))
        for i, d in enumerate(rows):
            try:
                file_ids = json.loads(d.file_ids or "[]")
            except Exception:
                file_ids = []
            url = ""
            try:
                from core.dashboard_server import get_global_server
                server = get_global_server()
                if server.running:
                    url = server.url_for(d.html_path or "")
            except Exception:
                url = ""
            items = [
                d.name or "AI可视化大屏",
                f"v{d.version}",
                str(len(file_ids)),
                d.updated_at.strftime("%Y-%m-%d %H:%M") if d.updated_at else "",
                d.html_path or "",
                url,
            ]
            for j, val in enumerate(items):
                it = QTableWidgetItem(str(val))
                if j == 0:
                    it.setData(Qt.ItemDataRole.UserRole, d.id)
                self.table.setItem(i, j, it)
        if rows:
            self.table.resizeRowsToContents()

    def _open_html(self, path):
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "提示", "大屏文件不存在或已被删除")
            return
        try:
            import subprocess
            if os.name == "nt":
                subprocess.Popen(["start", path], shell=True)
            else:
                subprocess.Popen(["open", path])
        except Exception:
            pass

    def _on_open_item(self, item):
        row = item.row()
        if 0 <= row < len(self._rows):
            self._open_html(self._rows[row].html_path or "")

    def _on_context_menu(self, pos):
        row = self.table.rowAt(pos.y())
        if row < 0 or row >= len(self._rows):
            return
        d = self._rows[row]
        menu = QMenu(self)
        menu.addAction("🌐 打开大屏", lambda: self._open_html(d.html_path or ""))
        menu.addAction("📄 复制文件路径", lambda: self._copy_text(d.html_path or ""))
        menu.addSeparator()
        # 历史版本（同会话其它版本）
        try:
            from app.database import Dashboard
            with self.db.session() as s:
                versions = s.query(Dashboard).filter(
                    Dashboard.conversation_id == d.conversation_id,
                    Dashboard.id != d.id
                ).order_by(Dashboard.version.desc()).all()
            if versions:
                submenu = menu.addMenu("🕘 历史版本")
                for v in versions[:10]:
                    label = f"v{v.version} · {v.updated_at.strftime('%m-%d %H:%M')}"
                    submenu.addAction(label, lambda p=v.html_path: self._open_html(p))
        except Exception:
            pass
        menu.addAction("🗑️ 删除记录", lambda: self._on_delete(d.id))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _copy_text(self, text):
        try:
            from PyQt6.QtGui import QGuiApplication
            QGuiApplication.clipboard().setText(text)
        except Exception:
            pass

    def _on_delete(self, did):
        reply = QMessageBox.question(self, "确认", "删除此大屏记录？",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                with self.db.session() as s:
                    from app.database import Dashboard
                    s.query(Dashboard).filter(Dashboard.id == did).delete()
            except Exception:
                pass
            self._load_data()

    def on_activate(self):
        self._load_data()
