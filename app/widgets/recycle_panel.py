"""
智汇中枢 - 回收站面板
管理已删除的知识库、文件和分析记录
"""

from datetime import datetime, timedelta

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame,
    QMessageBox, QAbstractItemView
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor


class RecyclePanel(QWidget):
    """回收站面板"""

    def __init__(self, config, db, main_window):
        super().__init__()
        self.config = config
        self.db = db
        self.main_window = main_window
        self._init_ui()
        self._load_data()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # 顶部标题栏
        top_layout = QHBoxLayout()
        title = QLabel("🗑️ 回收站")
        title.setObjectName("sectionTitle")
        top_layout.addWidget(title)
        top_layout.addStretch()

        self.restore_all_btn = QPushButton("  🔄  恢复全部")
        self.restore_all_btn.setObjectName("primaryButton")
        self.restore_all_btn.clicked.connect(self._on_restore_all)
        top_layout.addWidget(self.restore_all_btn)

        self.refresh_btn = QPushButton("  🔄  刷新")
        self.refresh_btn.clicked.connect(self._load_data)
        top_layout.addWidget(self.refresh_btn)

        self.clear_all_btn = QPushButton("  🗑️  一键清空")
        self.clear_all_btn.clicked.connect(self._on_clear_all)
        top_layout.addWidget(self.clear_all_btn)

        layout.addLayout(top_layout)

        # 说明
        self.hint_label = QLabel("已删除的项目保留30天，过期将自动清理。当前回收站为空。")
        self.hint_label.setStyleSheet("color: #888; font-size: 13px; padding-bottom: 8px;")
        layout.addWidget(self.hint_label)

        # 回收站列表
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["类型", "名称", "删除时间", "过期时间", "剩余天数"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 120)
        self.table.setColumnWidth(2, 160)
        self.table.setColumnWidth(3, 160)
        self.table.setColumnWidth(4, 100)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self._on_restore_item)

        layout.addWidget(self.table, 1)

        # 操作提示
        tip = QLabel("💡 双击项目可恢复 | 右键可选择操作")
        tip.setStyleSheet("color: #999; font-size: 12px;")
        layout.addWidget(tip)

    def _load_data(self):
        """加载回收站数据"""
        items = self.db.list_recycle_bin()
        now = datetime.now()

        self.table.setRowCount(len(items))
        for row, item in enumerate(items):
            type_names = {
                "knowledge_base": "知识库",
                "folder": "文件夹",
                "file": "文件",
                "analysis": "分析记录",
            }
            self.table.setItem(row, 0, QTableWidgetItem(
                type_names.get(item.item_type, item.item_type)))

            self.table.setItem(row, 1, QTableWidgetItem(item.item_name))
            self.table.setItem(row, 2, QTableWidgetItem(
                item.deleted_at.strftime("%Y-%m-%d %H:%M") if item.deleted_at else ""))

            expires_str = item.expires_at.strftime("%Y-%m-%d %H:%M") if item.expires_at else ""
            expires_item = QTableWidgetItem(expires_str)
            # 过期项目标红
            if item.expires_at and item.expires_at < now:
                expires_item.setForeground(QColor("#ff4d4f"))
            self.table.setItem(row, 3, expires_item)

            # 剩余天数
            if item.expires_at:
                remaining = (item.expires_at - now).days
                remaining_text = f"{remaining}天" if remaining >= 0 else "已过期"
                remaining_item = QTableWidgetItem(remaining_text)
                if remaining < 0:
                    remaining_item.setForeground(QColor("#ff4d4f"))
                self.table.setItem(row, 4, remaining_item)
            else:
                self.table.setItem(row, 4, QTableWidgetItem("-"))

            # 存储ID
            self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, item.id)

        # 更新提示
        if items:
            self.hint_label.setText(f"已删除的项目保留30天，过期将自动清理。当前共 {len(items)} 项。")
        else:
            self.hint_label.setText("回收站为空。删除的知识库、文件和分析记录将出现在这里。")

    def _on_restore_item(self, index):
        """恢复单个项目"""
        try:
            row = index.row()
            rb_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            name = self.table.item(row, 1).text() if self.table.item(row, 1) else ""
            if rb_id:
                self.db.restore_item(rb_id)
                self._load_data()
                self.db.add_log("INFO", "recycle", "restore", f"恢复: {name}")
        except Exception:
            pass

    def _on_restore_all(self):
        """恢复全部"""
        try:
            reply = QMessageBox.question(
                self, "确认恢复",
                "确定要恢复回收站中所有项目吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                items = self.db.list_recycle_bin()
                for item in items:
                    self.db.restore_item(item.id)
                self._load_data()
                QMessageBox.information(self, "恢复完成", "已恢复所有项目")
                self.db.add_log("INFO", "recycle", "restore_all",
                                f"恢复全部 {len(items)} 项")
        except Exception:
            pass

    def _on_clear_all(self):
        """一键清空"""
        try:
            reply = QMessageBox.question(
                self, "确认清空",
                "确定要永久清空回收站吗？\n此操作不可撤销！",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                with self.db.session() as s:
                    from app.database import RecycleBin, KnowledgeBase, File
                    expired = s.query(RecycleBin).all()
                    for rb in expired:
                        if rb.item_type == "knowledge_base":
                            s.query(KnowledgeBase).filter(
                                KnowledgeBase.id == rb.item_id).delete()
                        elif rb.item_type == "file":
                            s.query(File).filter(
                                File.id == rb.item_id).delete()
                        s.delete(rb)
                self._load_data()
                QMessageBox.information(self, "清空完成", "回收站已清空")
                self.db.add_log("INFO", "recycle", "clear_all", "清空回收站")
        except Exception:
            pass

    def on_activate(self):
        """页面激活时刷新"""
        self._load_data()
        # 清理过期项目
        self.db.clean_expired_items()
