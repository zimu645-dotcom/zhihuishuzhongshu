"""
智汇中枢 - 知识库管理面板
知识库-文件夹-文件三级结构管理
"""

import os
import json
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTreeWidget, QTreeWidgetItem, QFileDialog, QMessageBox,
    QInputDialog, QSplitter, QTableWidget, QTableWidgetItem,
    QHeaderView, QMenu, QFrame, QLineEdit, QTabWidget,
    QTextEdit, QProgressBar, QScrollArea, QAbstractItemView,
    QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QTimer, QFileSystemWatcher
from PyQt6.QtGui import QAction, QFont, QColor, QBrush, QIcon


class KnowledgePanel(QWidget):
    """知识库管理面板"""

    def __init__(self, config, db, main_window):
        super().__init__()
        self.config = config
        self.db = db
        self.main_window = main_window
        self.current_kb = None
        self.current_folder = None
        self._init_ui()
        self._load_data()
        # 启动上传文件夹监听（实时同步）
        self._start_folder_watch()

    def _start_folder_watch(self):
        """监听 uploads 文件夹，实时同步"""
        self._known_files = set()
        self._watch_timer = QTimer(self)
        self._watch_timer.setInterval(2000)
        self._watch_timer.timeout.connect(self._check_uploads)
        self._watch_timer.start()
        self._fs_watcher = QFileSystemWatcher(self)
        self._fs_watcher.directoryChanged.connect(self._on_fs_change)
        QTimer.singleShot(1000, self._init_watch_dirs)

    def _on_fs_change(self, path):
        """文件系统变化时立即检查"""
        QTimer.singleShot(300, self._check_uploads)

    def _init_watch_dirs(self):
        """初始化监听目录和已知文件列表"""
        upload_dir = self.config.upload_dir
        if not upload_dir or not os.path.exists(upload_dir):
            return
        self._fs_watcher.addPath(upload_dir)
        for root, dirs, _ in os.walk(upload_dir):
            for d in dirs:
                self._fs_watcher.addPath(os.path.join(root, d))
        current = set()
        for root, _, files in os.walk(upload_dir):
            for name in files:
                if not name.startswith('.'):
                    current.add(os.path.join(root, name))
        self._known_files = current
    def _check_uploads(self):
        """检查 uploads 文件夹变化（递归扫描所有子目录）"""
        upload_dir = self.config.upload_dir
        if not upload_dir or not os.path.exists(upload_dir):
            return
        try:
            current_files = set()
            for root, dirs, files in os.walk(upload_dir):
                for name in files:
                    if not name.startswith('.'):
                        current_files.add(os.path.join(root, name))

            # 检测新增文件
            new_files = current_files - self._known_files
            for fp in sorted(new_files):
                self._auto_import_file(fp)

            # 检测删除文件（从数据库标记删除）
            deleted_files = self._known_files - current_files
            if deleted_files:
                from app.database import File, Folder, KnowledgeBase
                with self.db.session() as s:
                    for fp in sorted(deleted_files):
                        f = s.query(File).filter(File.storage_path == fp, File.is_deleted == False).first()
                        if f:
                            # 获取知识库名称
                            folder = s.query(Folder).filter(Folder.id == f.folder_id).first()
                            kb_name = "?"
                            if folder:
                                kb = s.query(KnowledgeBase).filter(KnowledgeBase.id == folder.knowledge_base_id).first()
                                if kb:
                                    kb_name = kb.name
                            f.is_deleted = True
                            f.deleted_at = datetime.now()
                            self.db.add_log("INFO", "file", "auto_remove",
                                f"📂 知识库[{kb_name}] 文件已删除: {f.original_name} | 源文件: {os.path.basename(fp)}")

            self._known_files = current_files
        except Exception:
            pass

    def _auto_import_file(self, fp):
        """自动导入上传文件夹中的新文件"""
        try:
            # 查重：该路径已有未删除的登记记录就跳过。
            # 否则手动上传复制到 uploads 的瞬间会被文件夹监听器当成
            # "新文件"再导入一次，同一文件在库里出现两条记录
            # （已软删的记录不拦：用户删过又重新上传时应允许重新导入）
            from app.database import File as _FileModel
            with self.db.session() as s:
                dup = s.query(_FileModel).filter(
                    _FileModel.storage_path == fp,
                    _FileModel.is_deleted == False
                ).first()
            if dup:
                return

            name = os.path.basename(fp)
            # 从路径中提取知识库和文件夹信息
            rel_path = os.path.relpath(fp, self.config.upload_dir)
            path_parts = rel_path.replace("\\", "/").split("/")
            path_kb = path_parts[0] if len(path_parts) >= 1 else ""
            path_folder = path_parts[1] if len(path_parts) >= 2 else ""
            self.db.add_log("INFO", "file", "auto_import", f"发现新文件: {name}")

            # 确定目标知识库和文件夹
            kb_id = None
            folder_id = None
            kb_name = path_kb or "默认知识库"
            if self.current_kb:
                kb_id = self.current_kb.id
                kb_name = self.current_kb.name
                folders = self.db.list_folders(kb_id)
                # 尝试匹配路径中的文件夹名
                target_folder = path_folder or folders[0].name if folders else "自动导入"
                matched = [f for f in folders if f.name == target_folder]
                if matched:
                    folder_id = matched[0].id
                else:
                    folder_id = self.db.create_folder(kb_id, target_folder)

            if not kb_id:
                # 没有当前知识库时，创建默认知识库
                from app.database import KnowledgeBase
                with self.db.session() as s:
                    # 按路径中的知识库名匹配，不存在则创建
                    existing = s.query(KnowledgeBase).filter(
                        KnowledgeBase.name == kb_name,
                        KnowledgeBase.is_deleted == False
                    ).first()
                    if existing:
                        kb_id = existing.id
                    else:
                        kb = KnowledgeBase(name=kb_name)
                        s.add(kb)
                        kb_id = kb.id
                    # 按路径中的文件夹名匹配
                    target_folder = path_folder or "默认文件夹"
                    folders = self.db.list_folders(kb_id)
                    matched = [f for f in folders if f.name == target_folder]
                    if matched:
                        folder_id = matched[0].id
                    else:
                        folder_id = self.db.create_folder(kb_id, target_folder)
                self._load_data()

            # 导入文件
            from core.file_processor import parse_file, chunk_text
            result = parse_file(fp)
            if result.get("status") == "success":
                content = result.get("content", "")
                file_type = result.get("file_type", "txt")
                file_record = self.db.create_file(
                    folder_id=folder_id,
                    original_name=name,
                    storage_path=fp,
                    file_type=file_type,
                    file_size=os.path.getsize(fp),
                )
                self.db.update_file_status(file_record.id, "parsed",
                    content_text=content,
                    quality_score=result.get("quality_score", 50))
                chunks = chunk_text(content)
                if chunks:
                    self.db.save_chunks(file_record.id, chunks)
                self.db.add_log("INFO", "file", "auto_import_ok",
                    f"📂 知识库[{kb_name}] 自动导入: {name} ({len(content)}字) | 源文件: {fp}")
            else:
                self.db.add_log("WARNING", "file", "auto_import_fail",
                    f"文件解析失败: {name} - {result.get('error', '?')}")
        except Exception as e:
            self.db.add_log("ERROR", "file", "auto_import_err",
                f"自动导入异常: {str(e)[:100]}")

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # ── 顶部标题栏 ──
        top_layout = QHBoxLayout()
        self.title_label = QLabel("知识库")
        self.title_label.setObjectName("sectionTitle")
        top_layout.addWidget(self.title_label)
        top_layout.addStretch()

        # 新建知识库按钮
        self.new_kb_btn = QPushButton("  ➕  新建知识库")
        self.new_kb_btn.setObjectName("primaryButton")
        self.new_kb_btn.clicked.connect(self._on_new_knowledge_base)
        top_layout.addWidget(self.new_kb_btn)

        # 上传文件按钮
        self.upload_btn = QPushButton("  📤  上传文件")
        self.upload_btn.setObjectName("primaryButton")
        self.upload_btn.clicked.connect(self._on_upload_file)
        top_layout.addWidget(self.upload_btn)

        layout.addLayout(top_layout)

        # ── 主体分割 ──
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左侧：知识库树
        left_panel = QFrame()
        left_panel.setObjectName("card")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(12, 12, 12, 12)

        left_title = QLabel("📂 知识库结构")
        left_title.setStyleSheet("font-weight: bold; font-size: 15px; padding-bottom: 8px;")
        left_layout.addWidget(left_title)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setAnimated(True)
        self.tree.setIndentation(20)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        self.tree.itemClicked.connect(self._on_tree_item_clicked)
        self.tree.setMinimumWidth(250)
        left_layout.addWidget(self.tree)

        splitter.addWidget(left_panel)

        # 右侧：文件列表 + 详情
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)

        # 文件列表标题
        self.file_header = QLabel("选择左侧知识库查看文件")
        self.file_header.setStyleSheet("font-size: 15px; color: #888; padding: 4px 0;")
        right_layout.addWidget(self.file_header)

        # 文件表格
        self.file_table = QTableWidget()
        self.file_table.setColumnCount(5)
        self.file_table.setHorizontalHeaderLabels(["文件名", "类型", "大小", "状态", "上传时间"])
        self.file_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.file_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.file_table.setAlternatingRowColors(True)
        self.file_table.horizontalHeader().setStretchLastSection(True)
        self.file_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.file_table.setColumnWidth(1, 80)
        self.file_table.setColumnWidth(2, 100)
        self.file_table.setColumnWidth(3, 100)
        self.file_table.setColumnWidth(4, 160)
        self.file_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_table.customContextMenuRequested.connect(self._on_file_context_menu)
        right_layout.addWidget(self.file_table)

        splitter.addWidget(right_panel)
        splitter.setSizes([300, 700])

        layout.addWidget(splitter, 1)

    def _load_data(self):
        """加载知识库列表"""
        self.tree.clear()
        kbs = self.db.list_knowledge_bases()

        for kb in kbs:
            kb_item = QTreeWidgetItem(self.tree)
            kb_item.setText(0, f"📁 {kb.name}")
            kb_item.setData(0, Qt.ItemDataRole.UserRole, {
                "type": "kb",
                "id": kb.id
            })
            kb_item.setToolTip(0, kb.description or kb.name)

            # 加载子文件夹
            self._load_folders(kb.id, kb_item)

        self.file_table.setRowCount(0)
        self.file_header.setText("选择左侧知识库查看文件")

    def _load_folders(self, kb_id: int, parent_item: QTreeWidgetItem,
                      parent_folder_id: int = None):
        """递归加载文件夹"""
        folders = self.db.list_folders(kb_id, parent_folder_id)
        for folder in folders:
            item = QTreeWidgetItem(parent_item)
            item.setText(0, f"📂 {folder.name}")
            item.setData(0, Qt.ItemDataRole.UserRole, {
                "type": "folder",
                "id": folder.id,
                "kb_id": kb_id
            })
            # 递归子文件夹
            self._load_folders(kb_id, item, folder.id)

    def _on_tree_item_clicked(self, item: QTreeWidgetItem, column: int):
        """点击树节点"""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        if data["type"] == "kb":
            self.current_kb = self.db.get_knowledge_base(data["id"])
            self.current_folder = None
            self.file_header.setText(f"📁 {self.current_kb.name} - 所有文件")
            self.file_table.setRowCount(0)
            # 显示该知识库下所有文件（遍历所有文件夹）
            rows = []
            for i in range(item.childCount()):
                child = item.child(i)
                child_data = child.data(0, Qt.ItemDataRole.UserRole)
                if child_data and child_data["type"] == "folder":
                    files = self.db.list_files(child_data["id"])
                    for f in files:
                        rows.append(f)
            self._populate_file_table(rows)

        elif data["type"] == "folder":
            self.current_folder = data
            self.file_header.setText(f"📂 {item.text(0)}")
            files = self.db.list_files(data["id"])
            self._populate_file_table(files)

    def _populate_file_table(self, files):
        """填充文件表格"""
        self.file_table.setRowCount(len(files))
        for row, f in enumerate(files):
            name_item = QTableWidgetItem(f.original_name)
            name_item.setData(Qt.ItemDataRole.UserRole, f.id)  # 存储文件ID
            self.file_table.setItem(row, 0, name_item)
            self.file_table.setItem(row, 1, QTableWidgetItem(f.file_type.upper()))
            self.file_table.setItem(row, 2, QTableWidgetItem(self._format_size(f.file_size)))

            # 状态带颜色
            status_item = QTableWidgetItem(self._status_text(f.status))
            colors = {
                "pending": ("#faad14", "#fffbe6"),
                "parsed": ("#52c41a", "#f6ffed"),
                "parsing_failed": ("#ff4d4f", "#fff2f0"),
                "quality_low": ("#faad14", "#fffbe6"),
            }
            if f.status in colors:
                c, bg = colors[f.status]
                status_item.setForeground(QColor(c))
                status_item.setBackground(QColor(bg))
            self.file_table.setItem(row, 3, status_item)

            created = f.created_at.strftime("%Y-%m-%d %H:%M") if f.created_at else "-"
            self.file_table.setItem(row, 4, QTableWidgetItem(created))

    def _on_new_knowledge_base(self):
        """新建知识库"""
        name, ok = QInputDialog.getText(self, "新建知识库", "知识库名称:")
        if ok and name.strip():
            self.db.create_knowledge_base(name.strip())
            self._load_data()
            self.db.add_log("INFO", "knowledge_base", "create",
                            f"创建知识库: {name.strip()}")

    def _on_upload_file(self):
        """上传文件（无文件夹时自动创建默认文件夹）"""
        if not self.current_folder:
            # 如果没选文件夹，尝试找当前知识库的默认文件夹
            if self.current_kb:
                folders = self.db.list_folders(self.current_kb.id)
                default = None
                for f in folders:
                    if f.name == "默认文件夹" or f.name == "默认":
                        default = f
                        break
                if not default and folders:
                    default = folders[0]
                if default:
                    self.current_folder = {"type": "folder", "id": default.id, "kb_id": self.current_kb.id}
                else:
                    # 创建默认文件夹
                    new_folder = self.db.create_folder(self.current_kb.id, "默认文件夹")
                    self.current_folder = {"type": "folder", "id": new_folder.id, "kb_id": self.current_kb.id}
                    self._load_data()
            else:
                QMessageBox.information(self, "提示", "请先在左侧选择一个知识库或文件夹")
                return

        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "选择文件",
            "",
            "所有支持的文件 (*.txt *.md *.pdf *.docx *.xlsx *.pptx "
            "*.png *.jpg *.jpeg *.csv *.json);;所有文件 (*)"
        )

        if not file_paths:
            return

        for file_path in file_paths:
            self._import_single_file(file_path)

    def _import_single_file(self, file_path: str):
        """导入单个文件并自动解析"""
        try:
            import hashlib
            import shutil
            file_name = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)
            _, ext = os.path.splitext(file_name)
            ext = ext.lower().lstrip(".")

            # 类型映射
            type_map = {
                "txt": "txt", "md": "md", "pdf": "pdf",
                "docx": "docx", "xlsx": "xlsx", "pptx": "pptx",
                "png": "img", "jpg": "img", "jpeg": "img",
                "gif": "img", "bmp": "img", "webp": "img",
                "csv": "csv", "json": "json",
            }
            file_type = type_map.get(ext, "other")

            # 计算MD5
            md5 = hashlib.md5()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    md5.update(chunk)
            md5_hash = md5.hexdigest()

            # 复制到上传目录（按知识库/文件夹分组）
            kb_name = "未分类"
            folder_name = "未分类"
            if self.current_kb:
                kb_name = self.current_kb.name
            if self.current_folder:
                from app.database import Folder as _Fld, KnowledgeBase as _KB
                with self.db.session() as s:
                    fld = s.query(_Fld).filter(_Fld.id == self.current_folder["id"]).first()
                    if fld:
                        folder_name = fld.name
                        kb = s.query(_KB).filter(_KB.id == fld.knowledge_base_id).first()
                        if kb:
                            kb_name = kb.name
            # 清理非法文件名字符
            safe_kb = "".join(c for c in kb_name if c.isalnum() or c in " _-")
            safe_fld = "".join(c for c in folder_name if c.isalnum() or c in " _-")
            sub_dir = os.path.join(self.config.upload_dir, safe_kb, safe_fld)
            os.makedirs(sub_dir, exist_ok=True)
            dest_name = f"{md5_hash[:8]}_{file_name}"
            dest_path = os.path.join(sub_dir, dest_name)
            # 预先登记到监听器的已知文件集合，防止复制动作触发
            # 文件夹监听器把本次上传误判为"新文件"再自动导入一遍（重复记录）
            try:
                self._known_files.add(dest_path)
            except Exception:
                pass
            # 同一文件（MD5 相同）之前已导入过且未被删除就不再重复导入
            from app.database import File as _FileModel
            with self.db.session() as s:
                dup = s.query(_FileModel).filter(
                    _FileModel.storage_path == dest_path,
                    _FileModel.is_deleted == False
                ).first()
            if dup:
                return
            shutil.copy2(file_path, dest_path)

            # 写入数据库
            file_record = self.db.create_file(
                folder_id=self.current_folder["id"],
                original_name=file_name,
                storage_path=dest_path,
                file_type=file_type,
                file_size=file_size,
                md5_hash=md5_hash
            )

            # ── 自动解析文件内容 ──
            from core.file_processor import parse_file, chunk_text
            result = parse_file(dest_path)

            if result["success"]:
                # 保存解析结果
                self.db.update_file_status(
                    file_record.id,
                    status="parsed",
                    content_text=result["content"],
                    quality_score=result["quality_score"],
                    chunk_count=len(chunk_text(result["content"]))
                )
                # 保存分块
                chunks = chunk_text(result["content"])
                self.db.save_chunks(file_record.id, chunks)

                status_text = "✅ 已解析"
                quality = result["quality_score"]

                # 低质量警告
                if quality < 40:
                    status_text = "⚠️ 低质量"
                    self.db.update_file_status(file_record.id, status="quality_low")
            else:
                self.db.update_file_status(
                    file_record.id,
                    status="parsing_failed",
                    quality_score=0
                )
                status_text = "❌ 解析失败"

            self.db.add_log("INFO", "file", "upload",
                            f"上传文件: {file_name} [{status_text}]",
                            {"size": file_size, "type": file_type,
                             "quality": result.get("quality_score", 0),
                             "content_len": len(result.get("content", ""))})

        except Exception as e:
            QMessageBox.warning(self, "导入失败", f"文件 {os.path.basename(file_path)} 导入失败:\n{str(e)}")
            self.db.add_log("ERROR", "file", "upload_failed",
                            f"文件导入失败: {file_path}", {"error": str(e)})

        # 刷新文件列表
        if self.current_folder:
            files = self.db.list_files(self.current_folder["id"])
            self._populate_file_table(files)

    def _on_tree_context_menu(self, pos):
        """树节点右键菜单"""
        item = self.tree.itemAt(pos)
        if not item:
            return

        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        menu = QMenu(self)

        if data["type"] == "kb":
            new_folder_action = QAction("新建文件夹", self)
            new_folder_action.triggered.connect(
                lambda: self._on_new_folder(data["id"]))
            menu.addAction(new_folder_action)

            rename_action = QAction("重命名", self)
            rename_action.triggered.connect(
                lambda: self._on_rename_kb(data["id"]))
            menu.addAction(rename_action)

            menu.addSeparator()
            delete_action = QAction("删除知识库", self)
            delete_action.setIcon(QIcon())
            delete_action.triggered.connect(
                lambda: self._on_delete_kb(data["id"]))
            menu.addAction(delete_action)

        elif data["type"] == "folder":
            new_folder_action = QAction("新建子文件夹", self)
            new_folder_action.triggered.connect(
                lambda: self._on_new_sub_folder(data))
            menu.addAction(new_folder_action)

            rename_action = QAction("重命名", self)
            rename_action.triggered.connect(
                lambda: self._on_rename_folder(data["id"]))
            menu.addAction(rename_action)

            upload_action = QAction("上传文件到此文件夹", self)
            upload_action.triggered.connect(
                lambda: self._on_upload_to_folder(data))
            menu.addAction(upload_action)

            menu.addSeparator()
            delete_action = QAction("删除文件夹", self)
            delete_action.triggered.connect(
                lambda: self._on_delete_folder(data["id"]))
            menu.addAction(delete_action)

        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _on_new_folder(self, kb_id: int):
        name, ok = QInputDialog.getText(self, "新建文件夹", "文件夹名称:")
        if ok and name.strip():
            self.db.create_folder(kb_id, name.strip())
            self._load_data()
            self.db.add_log("INFO", "knowledge_base", "create_folder",
                            f"创建文件夹: {name.strip()}")

    def _on_new_sub_folder(self, parent_data: dict):
        name, ok = QInputDialog.getText(self, "新建子文件夹", "文件夹名称:")
        if ok and name.strip():
            self.db.create_folder(
                parent_data["kb_id"], name.strip(),
                parent_id=parent_data["id"]
            )
            self._load_data()

    def _on_rename_kb(self, kb_id: int):
        try:
            kb = self.db.get_knowledge_base(kb_id)
            if not kb:
                return
            name, ok = QInputDialog.getText(self, "重命名", "新名称:", text=kb.name)
            if ok and name.strip():
                with self.db.session() as s:
                    kb = s.merge(kb)
                    kb.name = name.strip()
                self.db.add_log("INFO", "knowledge_base", "rename",
                                f"知识库重命名: {name.strip()}")
        except Exception:
            pass

    def _on_delete_kb(self, kb_id: int):
        try:
            reply = QMessageBox.question(
                self, "确认删除",
                "确定要删除此知识库吗？\n"
                "所有文件和文件夹将移入回收站（可恢复解析后的文本），\n"
                "对应的磁盘文件将同步删除。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.db.delete_knowledge_base(kb_id)
                self._load_data()
                self.db.add_log("INFO", "knowledge_base", "delete", f"删除知识库")
        except Exception:
            pass

    def _on_rename_folder(self, folder_id: int):
        try:
            with self.db.session() as s:
                from app.database import Folder
                folder = s.query(Folder).filter(Folder.id == folder_id).first()
                if folder:
                    name, ok = QInputDialog.getText(self, "重命名", "新名称:", text=folder.name)
                    if ok and name.strip():
                        folder.name = name.strip()
                        self.db.add_log("INFO", "knowledge_base", "rename",
                                        f"文件夹重命名: {name.strip()}")
        except Exception:
            pass

    def _on_delete_folder(self, folder_id: int):
        try:
            reply = QMessageBox.question(
                self, "确认删除",
                "确定要删除此文件夹吗？\n其中的文件将移入回收站。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.db.delete_folder(folder_id)
                self._load_data()
                self.db.add_log("INFO", "knowledge_base", "delete", f"删除文件夹")
        except Exception:
            pass

    def _on_upload_to_folder(self, folder_data: dict):
        self.current_folder = folder_data
        self._on_upload_file()

    def _on_file_context_menu(self, pos):
        """文件右键菜单"""
        row = self.file_table.rowAt(pos.y())
        if row < 0:
            return

        menu = QMenu(self)

        preview_action = QAction("预览", self)
        menu.addAction(preview_action)

        menu.addSeparator()
        delete_action = QAction("删除", self)
        delete_action.triggered.connect(lambda: self._on_delete_file(row))
        menu.addAction(delete_action)

        menu.exec(self.file_table.viewport().mapToGlobal(pos))

    def _on_delete_file(self, row: int):
        """删除文件"""
        name_item = self.file_table.item(row, 0)
        if not name_item:
            return
        file_id = name_item.data(Qt.ItemDataRole.UserRole)
        file_name = name_item.text()

        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除 {file_name} 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes and file_id:
            self.db.delete_file(file_id)
            self.db.add_log("INFO", "file", "delete", f"删除文件: {file_name}")
            # 刷新文件列表
            if self.current_folder:
                files = self.db.list_files(self.current_folder["id"])
                self._populate_file_table(files)

    def on_activate(self):
        """页面激活时刷新"""
        self._load_data()

    @staticmethod
    def _format_size(size: int) -> str:
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        else:
            return f"{size / 1024 / 1024:.1f} MB"

    @staticmethod
    def _status_text(status: str) -> str:
        status_map = {
            "pending": "待处理",
            "parsed": "已解析",
            "parsing_failed": "解析失败",
            "quality_low": "低质量",
            "oversized": "超限压缩",
        }
        return status_map.get(status, status)
