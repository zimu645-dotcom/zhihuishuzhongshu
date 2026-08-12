"""
智汇中枢 - 分析记录面板
历史分析记录的查看、比对、合并导出
"""

import json
import os
from datetime import datetime, timedelta

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame,
    QSplitter, QTextEdit, QAbstractItemView, QMessageBox,
    QMenu, QCheckBox
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QAction, QColor, QBrush


class AnalysisPanel(QWidget):
    """分析记录面板"""

    def __init__(self, config, db, main_window):
        super().__init__()
        self.config = config
        self.db = db
        self.main_window = main_window
        self.selected_records = set()
        self._init_ui()
        self._load_data()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # 顶部标题栏
        top_layout = QHBoxLayout()
        title = QLabel("📊 分析记录")
        title.setObjectName("sectionTitle")
        top_layout.addWidget(title)
        top_layout.addStretch()

        self.merge_btn = QPushButton("  🔗  合并导出")
        self.merge_btn.setObjectName("primaryButton")
        self.merge_btn.clicked.connect(self._on_merge_export)
        self.merge_btn.setEnabled(False)
        top_layout.addWidget(self.merge_btn)

        self.refresh_btn = QPushButton("  🔄  刷新")
        self.refresh_btn.clicked.connect(self._load_data)
        top_layout.addWidget(self.refresh_btn)

        self.batch_delete_btn = QPushButton("  🗑️  批量删除")
        self.batch_delete_btn.clicked.connect(self._on_batch_delete)
        self.batch_delete_btn.setEnabled(False)
        top_layout.addWidget(self.batch_delete_btn)

        layout.addLayout(top_layout)

        # 说明
        hint = QLabel("勾选2条以上记录后可合并导出为汇总报告或PPT")
        hint.setStyleSheet("color: #888; font-size: 13px; padding: 0 0 8px 0;")
        layout.addWidget(hint)

        # 记录列表
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["", "标题", "分析类型", "摘要", "来源文件", "时间"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 40)   # 复选框列
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(3, 200)
        self.table.setColumnWidth(4, 150)
        self.table.setColumnWidth(5, 160)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)

        # 点击复选框
        self.table.cellClicked.connect(self._on_cell_clicked)

        layout.addWidget(self.table, 1)

    def _load_data(self):
        """加载分析记录"""
        self.table.setRowCount(0)
        records = self.db.list_analysis_records()

        self.table.setRowCount(len(records))
        for row, record in enumerate(records):
            # 复选框
            cb = QWidget()
            cb_layout = QHBoxLayout(cb)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            cb_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

            check = QCheckBox()
            check.stateChanged.connect(
                lambda state, r=row: self._on_check_changed(r, state))
            # 恢复选择状态
            if record.id in self.selected_records:
                check.setChecked(True)
            cb_layout.addWidget(check)
            self.table.setCellWidget(row, 0, cb)

            self.table.setItem(row, 1, QTableWidgetItem(record.title))

            type_names = {
                "query": "问答", "analysis": "数据分析",
                "chart": "图表", "report": "报告",
                "ppt": "PPT", "export": "导出"
            }
            self.table.setItem(row, 2, QTableWidgetItem(
                type_names.get(record.analysis_type, record.analysis_type)))

            summary = record.summary if record.summary else ""
            summary_item = QTableWidgetItem(summary[:80] + ("..." if len(summary) > 80 else ""))
            self.table.setItem(row, 3, summary_item)

            sources = json.loads(record.source_files) if record.source_files else []
            src_text = ", ".join(sources[:3]) if sources else "-"
            if len(sources) > 3:
                src_text += f"... (+{len(sources)-3}个)"
            self.table.setItem(row, 4, QTableWidgetItem(src_text))

            time_str = record.created_at.strftime("%Y-%m-%d %H:%M") if record.created_at else "-"
            self.table.setItem(row, 5, QTableWidgetItem(time_str))

            # 存储记录ID
            self.table.item(row, 1).setData(Qt.ItemDataRole.UserRole, record.id)

    def _on_cell_clicked(self, row: int, col: int):
        """点击单元格"""
        if col == 0:
            return  # 由复选框处理
        # 查看详情
        record_id = self.table.item(row, 1).data(Qt.ItemDataRole.UserRole)
        if record_id:
            self._show_detail(record_id)

    def _on_check_changed(self, row: int, state):
        """复选框状态变更"""
        record_id = self.table.item(row, 1).data(Qt.ItemDataRole.UserRole)
        if state == Qt.CheckState.Checked.value:
            self.selected_records.add(record_id)
        else:
            self.selected_records.discard(record_id)
        self.merge_btn.setEnabled(len(self.selected_records) >= 2)
        self.batch_delete_btn.setEnabled(len(self.selected_records) >= 1)

    def _show_detail(self, record_id: int):
        """显示分析记录详情（含下载功能）"""
        with self.db.session() as s:
            from app.database import AnalysisRecord
            record = s.query(AnalysisRecord).filter(
                AnalysisRecord.id == record_id).first()
            if record:
                from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QHBoxLayout
                dialog = QDialog(self)
                dialog.setWindowTitle(f"分析详情 - {record.title}")
                dialog.resize(700, 500)
                layout = QVBoxLayout(dialog)

                # 信息行
                info = QLabel(f"类型: {record.analysis_type}  |  时间: {record.created_at}")
                info.setStyleSheet("color: #888; font-size: 12px;")
                layout.addWidget(info)

                # 内容
                text = QTextEdit()
                text.setReadOnly(True)
                content = record.content or "(无内容)"
                text.setText(content)
                layout.addWidget(text, 1)

                # 操作按钮
                btn_layout = QHBoxLayout()
                download_btn = QPushButton("⬇️ 下载为文本")
                def do_download():
                    import os
                    path = os.path.join(
                        self.config.export_dir,
                        f"{record.title}_{record.id}.md"
                    )
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(content)
                    QMessageBox.information(dialog, "下载成功", f"已保存到:\n{path}")
                    self.db.add_log("INFO", "analysis", "download",
                                    f"下载分析记录: {record.title}",
                                    {"file": path})
                download_btn.clicked.connect(do_download)
                btn_layout.addWidget(download_btn)

                delete_btn = QPushButton("🗑️ 删除")
                delete_btn.setObjectName("dangerButton")
                def do_delete():
                    try:
                        from app.database import RecycleBin
                        with self.db.session() as s:
                            r = s.merge(record)
                            r.is_deleted = True
                            r.deleted_at = datetime.now()
                            s.add(RecycleBin(
                                item_type="analysis", item_id=r.id,
                                item_name=r.title,
                                expires_at=datetime.now() + timedelta(days=30)
                            ))
                        dialog.accept()
                        self._load_data()
                        self.db.add_log("INFO", "analysis", "delete",
                                        f"删除分析记录: {record.title}")
                    except Exception:
                        pass
                delete_btn.clicked.connect(do_delete)
                btn_layout.addWidget(delete_btn)

                # 生成的文件下载（图表、PPT等）
                sources = json.loads(record.source_files) if record.source_files else []
                for sf in sources:
                    if isinstance(sf, str) and os.path.exists(sf):
                        fname = os.path.basename(sf)
                        dl_btn = QPushButton(f"⬇️ {fname[:20]}")
                        dl_btn.setFixedHeight(28)
                        dl_btn.setStyleSheet("font-size:11px;border:1px solid #1a73e8;border-radius:4px;padding:2px 8px;color:#1a73e8;")
                        dl_btn.clicked.connect(lambda checked, p=sf: self._open_file(p))
                        btn_layout.addWidget(dl_btn)

                        btn_layout.addStretch()
                layout.addLayout(btn_layout)

                dialog.exec()

    def _open_file(self, path):
        """用系统默认程序打开文件（下载的大屏/图表/报告等）"""
        try:
            import subprocess
            if not path or not os.path.exists(path):
                QMessageBox.warning(self, "提示", "文件不存在或已被移动")
                return
            if os.name == "nt":
                subprocess.Popen(["start", path], shell=True)
            else:
                subprocess.Popen(["open", path])
        except Exception:
            pass

    def _on_merge_export(self):
        """合并导出选中的记录"""
        if len(self.selected_records) < 2:
            QMessageBox.information(self, "提示", "请至少选择2条记录")
            return

        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "合并导出", "导出名称:")
        if not (ok and name.strip()):
            return

        # 获取所选记录
        records = []
        with self.db.session() as s:
            from app.database import AnalysisRecord
            for rid in self.selected_records:
                record = s.query(AnalysisRecord).filter(
                    AnalysisRecord.id == rid).first()
                if record:
                    records.append(record)

        # 按时间排序
        records.sort(key=lambda r: r.created_at)

        # 生成合并内容
        parts = []
        for i, r in enumerate(records):
            parts.append(f"# {i+1}. {r.title}\n\n{r.summary}\n\n")

        merged_content = "\n---\n".join(parts)

        # 保存导出文件
        output_path = os.path.join(
            self.config.export_dir,
            f"{name.strip()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        )
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(merged_content)

        QMessageBox.information(self, "导出成功",
                                f"已导出到:\n{output_path}")

        self.db.add_log("INFO", "analysis", "merge_export",
                        f"合并导出 {len(records)} 条记录",
                        {"file": output_path})

    def _on_context_menu(self, pos):
        """右键菜单"""
        row = self.table.rowAt(pos.y())
        if row < 0:
            return

        from PyQt6.QtGui import QAction
        menu = QMenu(self)
        record_id = self.table.item(row, 1).data(Qt.ItemDataRole.UserRole)

        view_action = QAction("👁️ 查看详情", self)
        view_action.triggered.connect(lambda: self._show_detail(record_id))
        menu.addAction(view_action)

        download_action = QAction("⬇️ 下载", self)
        download_action.triggered.connect(lambda: self._download_single(record_id))
        menu.addAction(download_action)

        menu.addSeparator()
        delete_action = QAction("🗑️ 删除", self)
        delete_action.triggered.connect(lambda: self._on_delete(row))
        menu.addAction(delete_action)

        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _download_single(self, record_id: int):
        """下载单个记录"""
        with self.db.session() as s:
            from app.database import AnalysisRecord
            record = s.query(AnalysisRecord).filter(
                AnalysisRecord.id == record_id).first()
            if record:
                import os
                path = os.path.join(
                    self.config.export_dir,
                    f"{record.title}_{record.id}.md"
                )
                with open(path, "w", encoding="utf-8") as f:
                    f.write(record.content or "")
                QMessageBox.information(self, "下载成功", f"已保存到:\n{path}")
                self.db.add_log("INFO", "analysis", "download",
                                f"下载分析记录: {record.title}",
                                {"file": path})

    def _on_delete(self, row: int):
        """删除记录（加入回收站 + 记录日志）"""
        try:
            record_id = self.table.item(row, 1).data(Qt.ItemDataRole.UserRole)
            reply = QMessageBox.question(
                self, "确认", "确定删除此记录？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                from app.database import AnalysisRecord, RecycleBin
                with self.db.session() as s:
                    record = s.query(AnalysisRecord).filter(
                        AnalysisRecord.id == record_id).first()
                    if record:
                        record.is_deleted = True
                        record.deleted_at = datetime.now()
                        s.add(RecycleBin(
                            item_type="analysis", item_id=record.id,
                            item_name=record.title,
                            expires_at=datetime.now() + timedelta(days=30)
                        ))
                self.selected_records.discard(record_id)
                self._load_data()
                self.db.add_log("INFO", "analysis", "delete",
                                f"删除分析记录: {record.title if record else ''}")
        except Exception:
            pass

    def _on_batch_delete(self):
        """批量删除选中的记录"""
        try:
            if not self.selected_records:
                return
            reply = QMessageBox.question(
                self, "批量删除",
                f"确定要删除选中的 {len(self.selected_records)} 条记录吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                from app.database import AnalysisRecord, RecycleBin
                with self.db.session() as s:
                    for rid in list(self.selected_records):
                        record = s.query(AnalysisRecord).filter(
                            AnalysisRecord.id == rid).first()
                        if record:
                            record.is_deleted = True
                            record.deleted_at = datetime.now()
                            s.add(RecycleBin(
                                item_type="analysis", item_id=record.id,
                                item_name=record.title,
                                expires_at=datetime.now() + timedelta(days=30)
                            ))
                self.selected_records.clear()
                self._load_data()
                self.db.add_log("INFO", "analysis", "batch_delete",
                                f"批量删除 {len(self.selected_records)} 条记录")
        except Exception:
            pass

    def on_activate(self):
        """页面激活时刷新"""
        self._load_data()
