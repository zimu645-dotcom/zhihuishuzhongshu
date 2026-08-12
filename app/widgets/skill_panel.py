"""
智汇中枢 - 技能管理面板
安装、卸载、启用/禁用技能
"""

import os
import json

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QFileDialog, QMessageBox,
    QFrame, QAbstractItemView, QCheckBox,
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor

from core.skill_manager import list_skills, install_skill, uninstall_skill, toggle_skill, export_skill


class SkillPanel(QWidget):
    """技能管理面板"""

    def __init__(self, config, db, main_window):
        super().__init__()
        self.config = config
        self.db = db
        self.main_window = main_window
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        top = QHBoxLayout()
        title = QLabel("🧩 技能管理")
        title.setObjectName("sectionTitle")
        top.addWidget(title)
        top.addStretch()

        self.install_btn = QPushButton("  📥  安装技能 (.skill)")
        self.install_btn.setObjectName("primaryButton")
        self.install_btn.clicked.connect(self._on_install)
        top.addWidget(self.install_btn)

        layout.addLayout(top)

        hint = QLabel("技能可以让 AI 获得新的能力。安装后即可在对话中使用。")
        hint.setStyleSheet("color: #888; font-size: 13px;")
        layout.addWidget(hint)

        self.skill_list = QListWidget()
        self.skill_list.setFrameShape(QFrame.Shape.NoFrame)
        self.skill_list.setSpacing(4)
        layout.addWidget(self.skill_list, 1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(self.status_label)

        self._refresh()

    def _refresh(self):
        """刷新技能列表"""
        self.skill_list.clear()
        skills = list_skills()

        for skill in skills:
            name = skill.get("name", "未知")
            desc = skill.get("description", "")
            ver = skill.get("version", "1.0")
            enabled = skill.get("enabled", True)
            is_builtin = skill.get("builtin", False)

            w = QWidget()
            lo = QHBoxLayout(w)
            lo.setContentsMargins(12, 8, 12, 8)
            lo.setSpacing(8)

            cb = QCheckBox()
            cb.setChecked(enabled)
            cb.setEnabled(not is_builtin)
            if not is_builtin:
                cb.stateChanged.connect(lambda st, n=name: self._on_toggle(n, st))
            lo.addWidget(cb)

            info_lo = QVBoxLayout()
            info_lo.setSpacing(2)
            name_label = QLabel(f"🧩 {name}")
            name_label.setStyleSheet("font-size: 14px; font-weight: 600; color: #1a1a1a;")
            info_lo.addWidget(name_label)

            desc_label = QLabel(desc)
            desc_label.setStyleSheet("font-size: 12px; color: #888;")
            desc_label.setWordWrap(True)
            info_lo.addWidget(desc_label)

            tag_text = "内置" if is_builtin else f"v{ver}"
            tag = QLabel(tag_text)
            tag.setStyleSheet("font-size: 11px; color: #999; background: #f5f5f5; padding: 2px 8px; border-radius: 4px;")
            tag.setFixedHeight(22)
            info_lo.addWidget(tag)

            lo.addLayout(info_lo, 1)

            if not is_builtin:
                export_btn = QPushButton("📤 导出")
                export_btn.setFixedHeight(28)
                export_btn.setStyleSheet("font-size: 12px; border: 1px solid #d9d9d9; border-radius: 4px; padding: 2px 10px;")
                export_btn.clicked.connect(lambda checked, n=name: self._on_export(n))
                lo.addWidget(export_btn)

                del_btn = QPushButton("🗑️ 卸载")
                del_btn.setFixedHeight(28)
                del_btn.setStyleSheet("font-size: 12px; border: 1px solid #ea4335; border-radius: 4px; padding: 2px 10px; color: #ea4335;")
                del_btn.clicked.connect(lambda checked, n=name: self._on_uninstall(n))
                lo.addWidget(del_btn)

            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 90))
            self.skill_list.addItem(item)
            self.skill_list.setItemWidget(item, w)

        self.status_label.setText(f"共 {len(skills)} 个技能 | 勾选=启用，取消勾选=禁用")

    def _on_install(self):
        """安装本地技能"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择技能包", "",
            "技能包 (*.skill *.zip);;所有文件 (*)"
        )
        if not path:
            return

        success, msg = install_skill(path, self.db.add_log)
        if success:
            self._refresh()
        QMessageBox.information(self, "安装技能", msg)

    def _on_uninstall(self, name):
        """卸载技能"""
        reply = QMessageBox.question(
            self, "确认卸载", f"确定要卸载技能「{name}」吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            success, msg = uninstall_skill(name, self.db.add_log)
            if success:
                self._refresh()
            QMessageBox.information(self, "卸载技能", msg)

    def _on_toggle(self, name, state):
        """启用/禁用"""
        enabled = state == Qt.CheckState.Checked.value
        toggle_skill(name, enabled, self.db.add_log)

    def _on_export(self, name):
        """导出技能"""
        path = export_skill(name, self.config.export_dir)
        if path:
            QMessageBox.information(self, "导出成功", f"技能已导出到:\n{path}")

    def on_activate(self):
        """页面激活"""
        self._refresh()
