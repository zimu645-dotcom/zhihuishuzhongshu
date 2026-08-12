"""
智汇中枢 - 智能会话面板
"""

import json
import os
import time
import re
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTextEdit, QListWidget, QListWidgetItem, QSplitter,
    QFrame, QScrollArea, QFileDialog, QComboBox,
    QMessageBox, QSizePolicy, QAbstractItemView, QMenu
)
from PyQt6.QtCore import Qt, QSize, QTimer
from PyQt6.QtGui import QFont, QColor, QBrush, QAction, QTextCursor, QPainter, QPalette, QIcon

from core.ai_service import AIService


def _md_to_html(text: str) -> str:
    """Markdown \u2192 \u7cbe\u7f8e HTML"""
    import re
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r'`([^`]+)`', r'<code style="background:#f0f0f0;padding:2px 7px;border-radius:4px;font-size:13px;font-family:SFMono,Consolas,monospace;color:#d63384">\1</code>', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<b style="font-weight:600;color:#1a1a1a">\1</b>', text)
    text = re.sub(r'\*([^*]+)\*', r'<i>\1</i>', text)
    lines = text.split("\n")
    h = []
    in_tbl = False
    for line in lines:
        if line.strip().startswith("|") and line.strip().endswith("|"):
            if not in_tbl:
                h.append('<table style="width:100%;border-collapse:collapse;margin:10px 0;font-size:13px;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.04)">')
                in_tbl = True
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if any("---" in c for c in cells):
                h.append('<tr style="background:#f8f9fa">' + "".join(f'<th style="padding:10px 12px;border-bottom:2px solid #e0e0e0;font-weight:600;color:#555;text-align:left;font-size:12px">{c}</th>' for c in cells) + "</tr>")
            else:
                h.append('<tr style="border-bottom:1px solid #f0f0f0">' + "".join(f'<td style="padding:9px 12px;color:#333">{c}</td>' for c in cells) + "</tr>")
            continue
        if in_tbl and not (line.strip().startswith("|") and line.strip().endswith("|")):
            h.append("</table>")
            in_tbl = False
        if line.startswith("### "): h.append(f'<h3 style="margin:16px 0 8px;font-size:15px;font-weight:600;color:#1a1a1a">{line[4:]}</h3>')
        elif line.startswith("## "): h.append(f'<h2 style="margin:18px 0 10px;font-size:17px;font-weight:600;color:#1a1a1a">{line[3:]}</h2>')
        elif line.startswith("# "): h.append(f'<h1 style="margin:20px 0 12px;font-size:20px;font-weight:600;color:#1a1a1a">{line[2:]}</h1>')
        elif line.strip().startswith(("- ", "\u2022 ")): h.append(f'<li style="margin:3px 0 3px 16px;color:#444;line-height:1.7">{line.strip()[2:]}</li>')
        elif re.match(r"^\d+[.\u3001]\s", line.strip()):
            t = re.sub(r"^\d+[.\u3001]\s", "", line.strip())
            h.append(f'<li style="margin:3px 0 3px 16px;color:#444;line-height:1.7">{t}</li>')
        elif line.strip() == "---" or line.strip() == "***":
            h.append('<hr style="margin:16px 0;border:none;border-top:1px solid #e0e0e0">')
        elif not line.strip():
            h.append('<br>')
        else:
            h.append(f'<p style="margin:5px 0;line-height:1.8;color:#333">{line}</p>')
    if in_tbl: h.append("</table>")
    return "".join(h)


def _extract_html_code(text):
    """从 AI 回复里提取完整 HTML 代码，返回 (html代码, 原文中需替换的整段)；无则 (None, None)。"""
    if not text:
        return None, None
    # 1) fenced 代码块 ```html ... ```
    m = re.search(r'```(?:html|HTML)?\s*([\s\S]*?)```', text)
    if m:
        content = m.group(1).strip()
        low = content.lower()
        if any(k in low for k in ("<html", "<!doctype", "<body", "<div")) or "<style" in low:
            return content, m.group(0)
    # 2) 裸 <html>...</html>
    m = re.search(r'(<html[^>]*>[\s\S]*?</html>)', text, re.IGNORECASE)
    if m:
        return m.group(1), m.group(1)
    # 3) <!DOCTYPE html> 开头到结尾
    m = re.search(r'(<!DOCTYPE html>[\s\S]*)', text, re.IGNORECASE)
    if m:
        return m.group(1), m.group(1)
    return None, None


class ChatPanel(QWidget):
    """智能会话面板"""

    def __init__(self, config, db, main_window):
        super().__init__()
        self.config = config
        self.db = db
        self.main_window = main_window
        self.current_conversation = None
        self.ai_service = AIService(db)
        self._responding_convs = {}
        self._conv_state = {}
        self._response_done = {}
        self._conv_list_width = 250
        self._conv_list_collapsed = False
        self._ai_generated_images = []
        # 后台预热大屏 ECharts 依赖（首次联网下载一次，避免生成大屏时卡界面）
        try:
            import threading as _th
            _static = getattr(self.config, "static_dir", None)
            if _static:
                from core.dashboard import ensure_echarts as _prewarm
                _th.Thread(target=lambda: _prewarm(_static), daemon=True).start()
        except Exception:
            pass
        self._init_ui()
        self._load_conversations()
        self._setup_enter_to_send()

    def _setup_enter_to_send(self):
        self.input_edit.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj == self.input_edit and event.type() == event.Type.KeyPress:
            key = event.key()
            mods = event.modifiers()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and mods == Qt.KeyboardModifier.NoModifier:
                self._on_send_message()
                return True
        return super().eventFilter(obj, event)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.left_panel = QFrame()
        self.left_panel.setObjectName("card")
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(8, 12, 8, 12)
        left_layout.setSpacing(8)
        left_header_layout = QHBoxLayout()
        left_header_layout.setSpacing(4)
        left_header = QLabel("💬 会话")
        left_header.setStyleSheet("font-weight: bold; font-size: 15px; padding: 0 8px 8px 8px;")
        left_header_layout.addWidget(left_header)
        left_header_layout.addStretch()
        self.conv_collapse_btn = QPushButton("◀")
        self.conv_collapse_btn.setFixedSize(26, 26)
        self.conv_collapse_btn.setStyleSheet("""
            QPushButton {
                border: 2px solid #1a73e8; border-radius: 13px; font-size: 12px;
                background: #e8f0fe; color: #1a73e8; font-weight: bold;
            }
            QPushButton:hover { background: #1a73e8; color: white; }
        """)
        self.conv_collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.conv_collapse_btn.clicked.connect(self._toggle_conv_list)
        left_header_layout.addWidget(self.conv_collapse_btn)
        left_layout.addLayout(left_header_layout)
        self.new_conv_btn = QPushButton("  ➕  新建会话")
        self.new_conv_btn.setObjectName("primaryButton")
        self.new_conv_btn.clicked.connect(self._on_new_conversation)
        left_layout.addWidget(self.new_conv_btn)
        self.conv_list = QListWidget()
        self.conv_list.setFrameShape(QFrame.Shape.NoFrame)
        self.conv_list.itemClicked.connect(self._on_conv_selected)
        self.conv_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.conv_list.customContextMenuRequested.connect(self._on_conv_context_menu)
        left_layout.addWidget(self.conv_list)
        self.splitter.addWidget(self.left_panel)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(16, 12, 16, 12)
        right_layout.setSpacing(12)
        self.chat_header_layout = QHBoxLayout()
        self.chat_header_layout.setSpacing(4)
        self.show_conv_btn = QPushButton("☰")
        self.show_conv_btn.setFixedSize(28, 28)
        self.show_conv_btn.setStyleSheet("""
            QPushButton {
                border: 2px solid #1a73e8; border-radius: 14px; font-size: 14px;
                background: #e8f0fe; color: #1a73e8; font-weight: bold;
            }
            QPushButton:hover { background: #1a73e8; color: white; }
        """)
        self.show_conv_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.show_conv_btn.clicked.connect(self._toggle_conv_list)
        self.show_conv_btn.setVisible(False)
        self.chat_header_layout.addWidget(self.show_conv_btn)
        self.chat_header = QLabel("💬 新会话")
        self.chat_header.setObjectName("sectionTitle")
        self.chat_header_layout.addWidget(self.chat_header)
        self.chat_header_layout.addStretch()
        right_layout.addLayout(self.chat_header_layout)
        ctx = QHBoxLayout()
        ctx.setSpacing(8)
        ctx.addWidget(QLabel("知识库:"))
        self.kb_selector = QComboBox()
        self.kb_selector.setMinimumWidth(160)
        ctx.addWidget(self.kb_selector)
        ctx.addWidget(QLabel("文件夹:"))
        self.folder_selector = QComboBox()
        self.folder_selector.setMinimumWidth(160)
        ctx.addWidget(self.folder_selector)
        ctx.addWidget(QLabel("文件:"))
        self.file_selector = QComboBox()
        self.file_selector.setMinimumWidth(180)
        ctx.addWidget(self.file_selector)
        self.kb_selector.currentIndexChanged.connect(self._on_kb_changed)
        self.folder_selector.currentIndexChanged.connect(self._on_folder_changed)
        ctx.addStretch()
        right_layout.addLayout(ctx)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setStyleSheet("background-color: transparent;")
        self.messages_widget = QWidget()
        self.messages_layout = QVBoxLayout(self.messages_widget)
        self.messages_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.messages_layout.setSpacing(16)
        self.messages_layout.setContentsMargins(0, 0, 0, 0)
        self.empty_label = QLabel("✨ 开始你的第一次对话吧！")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: #bbb; font-size: 16px; padding: 80px;")
        self.messages_layout.addWidget(self.empty_label)
        self.scroll_area.setWidget(self.messages_widget)
        right_layout.addWidget(self.scroll_area, 1)

        input_frame = QFrame()
        input_frame.setObjectName("card")
        input_layout = QVBoxLayout(input_frame)
        input_layout.setContentsMargins(12, 8, 12, 8)
        input_layout.setSpacing(8)
        self.input_edit = QTextEdit()
        self.input_edit.setPlaceholderText("输入你的问题... (Enter发送, Shift+Enter换行)")
        self.input_edit.setMaximumHeight(120)
        self.input_edit.setMinimumHeight(60)
        input_layout.addWidget(self.input_edit)
        action_bar = QHBoxLayout()
        action_bar.setSpacing(8)
        action_bar.addStretch()
        self.send_btn = QPushButton("🚀 发送")
        self.send_btn.setObjectName("primaryButton")
        self.send_btn.clicked.connect(self._on_send_message)
        action_bar.addWidget(self.send_btn)
        input_layout.addLayout(action_bar)
        right_layout.addWidget(input_frame)
        self.splitter.addWidget(right_panel)
        self.splitter.setSizes([250, 750])
        layout.addWidget(self.splitter)

    def _load_conversations(self, select_id=None):
        self.conv_list.blockSignals(True)
        self.conv_list.clear()
        convs = self.db.list_conversations()
        if not convs:
            conv = self.db.create_conversation("新会话")
            convs = [conv]
        sel_item = None
        for conv in convs:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, conv.id)
            item.setSizeHint(QSize(0, 54))
            self.conv_list.addItem(item)
            self.conv_list.setItemWidget(item, self._make_conv_widget(conv))
            if select_id and conv.id == select_id:
                sel_item = item
        target = sel_item or (self.conv_list.item(0) if self.conv_list.count() > 0 else None)
        if target:
            self.conv_list.setCurrentItem(target)
            cid = target.data(Qt.ItemDataRole.UserRole)
            self.current_conversation = self.db.get_conversation(cid)
            if self.current_conversation:
                self.chat_header.setText(f"💬 {self.current_conversation.title}")
            else:
                self.chat_header.setText("💬 会话已删除")
            self._load_messages()
        else:
            self.current_conversation = None
            self._clear_messages()
            self.chat_header.setText("💬 无会话")
        self.conv_list.blockSignals(False)
        self._load_kb_selector()

    def _load_kb_selector(self):
        cur_kb = self.kb_selector.currentData()
        cur_folder = self.folder_selector.currentData()
        cur_file = self.file_selector.currentData()
        self.kb_selector.blockSignals(True)
        self.kb_selector.clear()
        self.kb_selector.addItem("不使用知识库", None)
        for kb in self.db.list_knowledge_bases():
            self.kb_selector.addItem(f"📁 {kb.name}", kb.id)
        if cur_kb:
            i = self.kb_selector.findData(cur_kb)
            if i >= 0: self.kb_selector.setCurrentIndex(i)
        self.kb_selector.blockSignals(False)
        kb_id = cur_kb or self.kb_selector.currentData()
        self._load_folder_selector(kb_id)
        if cur_folder:
            i = self.folder_selector.findData(cur_folder)
            if i >= 0: self.folder_selector.setCurrentIndex(i)
        self._load_file_selector(kb_id, cur_folder or None)
        if cur_file:
            i = self.file_selector.findData(cur_file)
            if i >= 0: self.file_selector.setCurrentIndex(i)

    def _load_folder_selector(self, kb_id):
        self.folder_selector.blockSignals(True)
        self.folder_selector.clear()
        self.folder_selector.addItem("所有文件夹", None)
        if kb_id:
            for f in self.db.list_folders(kb_id):
                self.folder_selector.addItem(f"📂 {f.name}", f.id)
        self.folder_selector.blockSignals(False)

    def _load_file_selector(self, kb_id, folder_id=None):
        self.file_selector.blockSignals(True)
        self.file_selector.clear()
        self.file_selector.addItem("所有文件", None)
        if not kb_id:
            self.file_selector.blockSignals(False)
            return
        try:
            if folder_id:
                files = self.db.list_files(folder_id)
            else:
                files = self.db.list_files_by_knowledge_base(kb_id)
            for f in files:
                label = f.original_name or f"文件 {f.id}"
                if f.file_size:
                    size_str = f"{f.file_size / 1024:.0f}KB" if f.file_size < 1024*1024 else f"{f.file_size / 1024 / 1024:.1f}MB"
                    label += f" ({size_str})"
                self.file_selector.addItem(f"📄 {label}", f.id)
        except Exception:
            pass
        self.file_selector.blockSignals(False)

    def _on_kb_changed(self, index):
        kb_id = self.kb_selector.currentData()
        self._load_folder_selector(kb_id)
        self.folder_selector.setCurrentIndex(0)
        self._load_file_selector(kb_id)

    def _on_folder_changed(self, index):
        folder_id = self.folder_selector.currentData()
        kb_id = self.kb_selector.currentData()
        self._load_file_selector(kb_id, folder_id)

    def _make_conv_widget(self, conv):
        import json as _j
        w = QWidget()
        w.setObjectName("convItem")
        layout = QHBoxLayout(w)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        title = conv.title if len(conv.title) <= 20 else conv.title[:20] + "..."
        count = conv.message_count or 0
        prefix = "📌" if conv.is_pinned else "💬"
        title_label = QLabel(f"{prefix} {title}  ({count}条)")
        title_label.setStyleSheet("font-size: 13px; font-weight: bold;" if conv.is_pinned else "font-size: 13px;")
        info_layout.addWidget(title_label)
        tags = _j.loads(conv.tags) if conv.tags else []
        if tags:
            tag_label = QLabel("  ".join(f"#{t}" for t in tags[:3]))
            tag_label.setStyleSheet("font-size: 11px; color: #1890ff;")
            info_layout.addWidget(tag_label)
        ts = conv.updated_at or conv.created_at
        if ts:
            time_label = QLabel(ts.strftime("%m-%d %H:%M"))
            time_label.setStyleSheet("font-size: 10px; color: #aaa;")
            info_layout.addWidget(time_label)
        layout.addLayout(info_layout, 1)
        menu_btn = QPushButton("⋯")
        menu_btn.setFixedSize(28, 28)
        menu_btn.setStyleSheet("QPushButton{border:none;border-radius:14px;font-size:16px;color:#999;background:transparent}QPushButton:hover{background:#e0e0e0;color:#333}")
        menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        menu_btn.clicked.connect(lambda checked, c=conv, btn=menu_btn: self._show_conv_menu(c, btn))
        layout.addWidget(menu_btn)
        if conv.is_pinned:
            w.setStyleSheet("QWidget#convItem{background-color:#fff8e1;border-radius:8px;border:1px solid #ffe082}")
        return w

    def _show_conv_menu(self, conv, btn):
        menu = QMenu(self)
        if conv.is_pinned:
            menu.addAction("📌 取消置顶", lambda: self._on_toggle_pin(conv.id))
        else:
            menu.addAction("📌 置顶", lambda: self._on_toggle_pin(conv.id))
        menu.addAction("✏️ 重命名", lambda: self._on_rename_conv_id(conv.id))
        menu.addAction("🏷️ 管理标签", lambda: self._on_add_tag(conv.id))
        menu.addSeparator()
        menu.addAction("🗑️ 删除", lambda: self._on_delete_conv_id(conv.id))
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _on_toggle_pin(self, conv_id):
        with self.db.session() as s:
            from app.database import Conversation
            c = s.query(Conversation).filter(Conversation.id == conv_id).first()
            if c: c.is_pinned = not c.is_pinned; c.updated_at = datetime.now()
        self._load_conversations(select_id=conv_id)

    def _on_rename_conv_id(self, conv_id):
        from PyQt6.QtWidgets import QInputDialog
        conv = self.db.get_conversation(conv_id)
        if conv:
            name, ok = QInputDialog.getText(self, "重命名", "新名称:", text=conv.title)
            if ok and name.strip():
                with self.db.session() as s:
                    c = s.merge(conv); c.title = name.strip()
                self._load_conversations(select_id=conv_id)

    def _on_delete_conv_id(self, conv_id):
        reply = QMessageBox.question(self, "确认", "删除此会话？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            with self.db.session() as s:
                from app.database import Conversation
                s.query(Conversation).filter(Conversation.id == conv_id).delete()
            if self.current_conversation and self.current_conversation.id == conv_id:
                self.current_conversation = None
            self._load_conversations()

    def _on_add_tag(self, conv_id):
        import json as _j
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QLineEdit
        conv = self.db.get_conversation(conv_id)
        if not conv: return
        tags = _j.loads(conv.tags) if conv.tags else []
        dlg = QDialog(self); dlg.setWindowTitle(f"管理标签"); dlg.resize(350, 300)
        lo = QVBoxLayout(dlg)
        lst = QListWidget()
        for t in tags: lst.addItem(t)
        lo.addWidget(lst, 1)
        del_btn = QPushButton("🗑️ 删除选中")
        del_btn.clicked.connect(lambda: lst.takeItem(lst.currentRow()) if lst.currentRow() >= 0 else None)
        lo.addWidget(del_btn)
        al = QHBoxLayout()
        inp = QLineEdit(); inp.setPlaceholderText("新标签")
        al.addWidget(inp, 1)
        add_btn = QPushButton("➕ 添加")
        add_btn.clicked.connect(lambda: [lst.addItem(inp.text()), inp.clear()] if inp.text().strip() and not any(lst.item(i).text() == inp.text().strip() for i in range(lst.count())) else None)
        al.addWidget(add_btn)
        lo.addLayout(al)
        sv = QPushButton("💾 保存")
        def do_save():
            new = [lst.item(i).text() for i in range(lst.count())]
            with self.db.session() as s:
                from app.database import Conversation
                c = s.query(Conversation).filter(Conversation.id == conv_id).first()
                if c: c.tags = _j.dumps(new)
            dlg.accept()
            self._update_single_conv_widget(conv_id)
        sv.clicked.connect(do_save)
        lo.addWidget(sv)
        dlg.exec()

    def _update_single_conv_widget(self, conv_id):
        try:
            conv = self.db.get_conversation(conv_id)
            if not conv: return
            for i in range(self.conv_list.count()):
                item = self.conv_list.item(i)
                if item and item.data(Qt.ItemDataRole.UserRole) == conv_id:
                    self.conv_list.setItemWidget(item, self._make_conv_widget(conv)); break
        except: pass

    def _on_new_conversation(self):
        conv = self.db.create_conversation("新会话")
        self.current_conversation = conv
        self._clear_messages()
        self.chat_header.setText("💬 新会话")
        self._load_conversations(select_id=conv.id)

    def _on_conv_selected(self, item):
        conv_id = item.data(Qt.ItemDataRole.UserRole)
        self.current_conversation = self.db.get_conversation(conv_id)
        if self.current_conversation:
            self.chat_header.setText(f"💬 {self.current_conversation.title}")
            self._load_messages()
        # 切换会话时更新发送按钮状态
        self._update_send_btn()

    def _set_widgets_visible(self, layout, visible, keep_btn=None):
        """递归设置布局中所有部件的可见性"""
        if not layout:
            return
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if not item:
                continue
            if item.layout():
                self._set_widgets_visible(item.layout(), visible, keep_btn)
            w = item.widget()
            if w and w != keep_btn:
                w.setVisible(visible)

    def _toggle_conv_list(self):
        """折叠/展开会话列表"""
        if not self._conv_list_collapsed:
            self._conv_list_collapsed = True
            self._conv_list_width = self.splitter.sizes()[0]
            self._set_widgets_visible(self.left_panel.layout(), False, None)
            self.left_panel.setVisible(False)
            self.show_conv_btn.setVisible(True)
        else:
            self._conv_list_collapsed = False
            self.left_panel.setVisible(True)
            self._set_widgets_visible(self.left_panel.layout(), True, None)
            self.show_conv_btn.setVisible(False)
            sizes = self.splitter.sizes()
            total = sum(sizes)
            if total > self._conv_list_width:
                self.splitter.setSizes([self._conv_list_width, total - self._conv_list_width])

    def _update_send_btn(self):
        """根据当前会话是否在分析中，更新发送按钮状态"""
        cid = self.current_conversation.id if self.current_conversation else None
        if cid and cid in self._responding_convs:
            self.send_btn.setEnabled(False)
            self.send_btn.setText("⏳ 思考中...")
        else:
            self.send_btn.setEnabled(True)
            self.send_btn.setText("🚀 发送")

    def _on_conv_context_menu(self, pos):
        item = self.conv_list.itemAt(pos)
        if not item: return
        conv_id = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        menu.addAction("✏️ 重命名", lambda: self._on_rename_conv_id(conv_id))
        menu.addAction("🗑️ 删除", lambda: self._on_delete_conv_id(conv_id))
        menu.exec(self.conv_list.viewport().mapToGlobal(pos))

    def _on_rename_conv(self, item):
        conv_id = item.data(Qt.ItemDataRole.UserRole)
        self._on_rename_conv_id(conv_id)

    def _on_delete_conv(self, item):
        conv_id = item.data(Qt.ItemDataRole.UserRole)
        self._on_delete_conv_id(conv_id)

    def _load_messages(self):
        self._clear_messages()
        if not self.current_conversation:
            self.empty_label.show(); return
        cid = self.current_conversation.id
        msgs = self.db.get_messages(cid)
        if not msgs:
            self.empty_label.show()
        else:
            self.empty_label.hide()
            for m in msgs:
                self._add_message_bubble(m.role, m.content, m.content_type, m.feedback, m.id, m.msg_metadata)
        # 如果该会话正在响应中，显示思考中
        if cid in self._responding_convs:
            tl = QLabel("🤔 AI 正在分析...")
            tl.setStyleSheet("color: #888; font-size: 13px; padding: 12px;")
            tl.setObjectName("thinking_label")
            self.messages_layout.addWidget(tl)
        QTimer.singleShot(50, self._scroll_to_bottom)

    def _clear_messages(self):
        if hasattr(self, 'messages_widget') and self.messages_widget:
            self.messages_widget.deleteLater()
        nw = QWidget()
        nl = QVBoxLayout(nw)
        nl.setAlignment(Qt.AlignmentFlag.AlignTop)
        nl.setSpacing(16)
        nl.setContentsMargins(0, 0, 0, 0)
        self.empty_label = QLabel("✨ 开始你的第一次对话吧！")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: #bbb; font-size: 16px; padding: 80px;")
        nl.addWidget(self.empty_label)
        self.scroll_area.setWidget(nw)
        self.messages_widget = nw
        self.messages_layout = nl
        self.empty_label.show()
        self.update()

    def _add_message_bubble(self, role, content, content_type="text", feedback=None, msg_id=None, metadata=None):
        self.empty_label.hide()
        is_user = role == "user"
        bubble = QFrame()
        bubble.setObjectName("card")
        if is_user:
            bg = "#e3f0ff"
            border = "border:1px solid rgba(26,115,232,0.1)"
        else:
            bg = "#ffffff"
            border = "border:1px solid rgba(0,0,0,0.04)"
        bubble.setStyleSheet(f"QFrame#card{{background:{bg};{border};border-radius:14px;padding:14px}}")
        bubble.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bl = QVBoxLayout(bubble)
        bl.setContentsMargins(14, 8, 14, 8)
        bl.setSpacing(6)
        # 角色名
        rl = QLabel("你" if is_user else "🤖 智汇中枢")
        rl.setStyleSheet("font-weight:600;font-size:13px;color:#1a73e8" if is_user else "font-weight:600;font-size:13px;color:#555")
        bl.addWidget(rl)
        # 内容
        if is_user:
            cl = QLabel(content)
            cl.setWordWrap(True)
            cl.setStyleSheet("font-size:14px;line-height:1.8;color:#1a1a1a;padding:2px 0")
        else:
            cl = QLabel()
            cl.setTextFormat(Qt.TextFormat.RichText)
            cl.setText(_md_to_html(content))
            cl.setWordWrap(True)
            cl.setStyleSheet("font-size:14px;line-height:1.8;color:#333;padding:2px 0")
            cl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        cl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bl.addWidget(cl)
        # 显示附加图片（从元数据中读取）
        if metadata:
            try:
                import json as _j
                meta = _j.loads(metadata) if isinstance(metadata, str) else metadata or {}
                for img_path in (meta.get("images", []) or []):
                    if os.path.exists(img_path):
                        from PyQt6.QtGui import QPixmap
                        pix = QPixmap(img_path)
                        if not pix.isNull():
                            il = QLabel()
                            il.setPixmap(pix.scaledToWidth(560))
                            il.setStyleSheet("padding:4px 0")
                            bl.addWidget(il)
                            # 下载按钮
                            dl = QPushButton("⬇️ 下载图表")
                            dl.setFixedHeight(28)
                            dl.setStyleSheet("QPushButton{border:1px solid #1a73e8;border-radius:4px;padding:2px 12px;font-size:12px;color:#1a73e8} QPushButton:hover{background:#e8f0fe}")
                            dl.clicked.connect(lambda checked, p=img_path: self._download_file(p))
                            bl.addWidget(dl)
                # 显示附加文件（PPT等）
                for doc_path in (meta.get("files", []) or []):
                    if os.path.exists(doc_path):
                        dl = QPushButton("⬇️ 下载文件")
                        dl.setFixedHeight(28)
                        dl.setStyleSheet("QPushButton{border:1px solid #34a853;border-radius:4px;padding:2px 12px;font-size:12px;color:#34a853} QPushButton:hover{background:#e6f4ea}")
                        dl.clicked.connect(lambda checked, p=doc_path: self._download_file(p))
                        bl.addWidget(dl)
            except:
                pass
        # 底部操作栏（复制按钮 + AI回复的点赞/点踩）
        ar = QHBoxLayout()
        ar.setSpacing(6)
        copy_btn = QPushButton("📋 复制")
        copy_btn.setFixedHeight(28)
        copy_btn.setStyleSheet("QPushButton{border:1px solid #d9d9d9;border-radius:4px;padding:2px 10px;font-size:12px;color:#666} QPushButton:hover{border-color:#1a73e8;color:#1a73e8}")
        copy_btn.clicked.connect(lambda: self._copy_text(content))
        ar.addWidget(copy_btn)
        if not is_user and msg_id:
            lb = QPushButton(" 👍 "); lb.setFixedSize(42, 28)
            lb.setStyleSheet("border:1px solid #d9d9d9;border-radius:4px;font-size:15px")
            lb.clicked.connect(lambda checked, mid=msg_id: self._on_feedback(mid, 1))
            ar.addWidget(lb)
            db = QPushButton(" 👎 "); db.setFixedSize(46, 30)
            db.setStyleSheet("border:1px solid #d9d9d9;border-radius:4px;font-size:15px")
            db.clicked.connect(lambda checked, mid=msg_id: self._on_feedback(mid, -1))
            ar.addWidget(db)
            ar.addStretch()
        bl.addLayout(ar)
        c = QHBoxLayout()
        c.setContentsMargins(0, 0, 0, 0)
        if is_user:
            c.addStretch()
            c.addWidget(bubble, 0)
        else:
            c.addWidget(bubble, 1)
        self.messages_layout.addLayout(c)
        self._scroll_to_bottom()

    def _scroll_to_bottom(self):
        try:
            if hasattr(self, 'scroll_area') and self.scroll_area:
                sb = self.scroll_area.verticalScrollBar()
                sb.setValue(sb.maximum())
        except: pass

    def _on_feedback(self, msg_id, value):
        try:
            self.db.set_message_feedback(msg_id, value)
            if value == -1:
                reasons = ["答非所问", "数据错误", "格式混乱", "不完整", "其他"]
                from PyQt6.QtWidgets import QInputDialog
                reason, ok = QInputDialog.getItem(self, "反馈", "原因:", reasons, 0, False)
                if ok and reason:
                    self.db.set_message_feedback(msg_id, value, reason)
                    self.db.add_log("INFO", "user", "feedback", f"点踩: {reason}", {"msg_id": msg_id})
        except Exception:
            pass

    def _copy_text(self, text):
        try:
            from PyQt6.QtGui import QGuiApplication
            QGuiApplication.clipboard().setText(text)
        except: pass

    def _download_file(self, path):
        """用系统默认程序打开/下载文件"""
        try:
            import subprocess, platform
            if platform.system() == "Darwin":
                subprocess.Popen(["open", path])
            elif platform.system() == "Windows":
                subprocess.Popen(["start", path], shell=True)
            else:
                subprocess.Popen(["xdg-open", path])
        except: pass

    def _on_attach_file(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择文件", "", "所有文件 (*)")
        if files:
            self.input_edit.append(f"\n[已附加 {len(files)} 个文件]")

    def _on_send_message(self):
        try:
            self._do_send_message()
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            self.db.add_log("CRITICAL", "chat", "crash", f"发送崩溃: {str(e)}", {"trace": tb[:300]})
            if self.current_conversation:
                self._responding_convs.pop(self.current_conversation.id, None)
            self.send_btn.setEnabled(True)
            self.send_btn.setText("🚀 发送")
            if self.current_conversation:
                self._add_message_bubble("assistant", f"⚠️ 程序出错: {str(e)[:200]}")
                self.db.add_message(self.current_conversation.id, "assistant", f"⚠️ 程序出错: {str(e)[:200]}")

    def _do_send_message(self):
        text = self.input_edit.toPlainText().strip()
        if not text: return
        if not self.current_conversation: self._on_new_conversation()
        conv_id = self.current_conversation.id
        # 允许不同会话同时分析，同一会话不能重复发
        if conv_id in self._responding_convs: return
        self._response_done[conv_id] = False
        self.db.add_message(conv_id, "user", text)
        self._add_message_bubble("user", text)
        self.input_edit.clear()
        self._responding_convs[conv_id] = True
        self.send_btn.setEnabled(False)
        self.send_btn.setText("⏳ 思考中...")
        tl = QLabel("🤔 AI 正在分析...")
        tl.setStyleSheet("color: #888; font-size: 13px; padding: 12px;")
        self.empty_label.hide()
        self.messages_layout.addWidget(tl)
        self._scroll_to_bottom()

        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()

        # 后台准备文件内容
        title = text[:30] + ("..." if len(text) > 30 else "")
        with self.db.session() as s:
            conv = s.merge(self.current_conversation)
            if conv.message_count <= 1: conv.title = title
        messages = self.db.get_messages(conv_id, limit=20)
        history = [{"role": m.role, "content": m.content} for m in messages]
        kb_id = self.kb_selector.currentData()
        folder_id = self.folder_selector.currentData()
        file_id = self.file_selector.currentData()
        # 构建选择信息（让 AI 知道用户选了啥）
        sel_parts = []
        if kb_id:
            kb_text = self.kb_selector.currentText()
            sel_parts.append(f"知识库={kb_text}")
        if folder_id:
            sel_parts.append(f"文件夹={self.folder_selector.currentText()}")
        if file_id:
            sel_parts.append(f"文件={self.file_selector.currentText()}")
        selection_info = f"[用户当前选择的资源: {', '.join(sel_parts) if sel_parts else '无'}]"
        file_context = ""; file_ids = []; file_names = []; image_files = []
        if kb_id:
            try:
                files = []
                if file_id:
                    from app.database import File as _File
                    with self.db.session() as s:
                        f = s.query(_File).filter(_File.id == file_id).first()
                        if f: files = [f]
                elif folder_id:
                    files = self.db.list_files(folder_id)
                else:
                    files = self.db.list_files_by_knowledge_base(kb_id)
                if files:
                    file_ids = [f.id for f in files]; file_names = [f.original_name for f in files]
                    image_files = []
                    for f in files:
                        if f.file_type == "img" and f.storage_path and os.path.exists(f.storage_path):
                            image_files.append({"path": f.storage_path, "detail": "auto"})

                                            # 直接把所有文件内容发给 AI
                        file_parts = []
                        for _f in files:
                            _c = _f.content_text or ""
                            if _c:
                                file_parts.append(f"【{_f.original_name}】\n{_c[:5000]}")
                        if file_parts:
                            file_context = selection_info + "\n\n[知识库文件内容]\n" + "\n\n".join(file_parts) + f"\n[共 {len(file_ids)} 个文件]"
            except: pass

        # ── 大屏意图：注入结构化数据预览 + 上一版大屏 spec（供 AI 设计/调整大屏）──
        low_text = text.lower()
        is_dash = any(kw in low_text for kw in ("大屏", "看板", "dashboard", "html格式", "html 大屏"))
        is_adjust = any(kw in text for kw in ("调整", "优化", "修改", "改一下", "换主题", "换图表",
                                              "加一个", "加个", "布局", "配色", "改成", "重做"))
        if is_dash:
            # 0) 强约束：禁止输出 HTML 代码文本、禁止走 generate_chart PNG
            file_context += ("\n\n[要求] 用户要的是可打开的 HTML 可视化大屏。你【必须】调用"
                             "[TOOL] generate_dashboard 工具输出 spec(JSON)，由系统渲染成 HTML 文件并给出链接。"
                             "【绝对禁止】直接输出 HTML 代码文本；【绝对禁止】调用 generate_chart 生成 PNG 图片。"
                             "只用 generate_dashboard 一个工具。")
            # 1) 用 pandas 提取当前选中 xlsx/csv 的结构化数据预览，让 AI 第一次就知道数据结构
            try:
                from core.dashboard import extract_structured_data, build_data_preview
                tab_file = next((f for f in files if f.file_type in ("xlsx", "csv")), None) if files else None
                if tab_file:
                    sd = extract_structured_data(tab_file.storage_path, tab_file.file_type)
                    pv = build_data_preview(sd)
                    if pv:
                        file_context += f"\n\n[数据预览]\n{pv}"
            except Exception:
                pass
            # 2) 调整意图时，把该会话上一版 spec 注入上下文，让 AI 基于它修改
            if is_adjust:
                try:
                    from app.database import Dashboard as _Dash
                    with self.db.session() as s:
                        prev = s.query(_Dash).filter(
                            _Dash.conversation_id == conv_id
                        ).order_by(_Dash.version.desc()).first()
                    if prev:
                        file_context += (f"\n\n[上一版大屏 spec]\n{prev.spec}"
                                         f"\n(请基于此修改，输出一份完整的全新 spec)")
                except Exception:
                    pass

        if file_context and history:
            for i in range(len(history)-1, -1, -1):
                if history[i]["role"] == "user": history[i]["content"] += file_context; break
        model_key = self.ai_service.classify_task(text)
        self._ai_conv_id = conv_id  # 向后兼容的 fallback（仅单会话时使用）
        self._conv_state[conv_id] = {
            "history": history, "model_key": model_key, "label": tl,
            "file_ids": file_ids, "file_names": file_names,
            "file_context": file_context, "query": text,
            "images": image_files, "thread": None, "result": None,
            "gen_images": [],  # 本会话生成的图片/文件，按会话隔离
            "dash_request": is_dash,  # 本次是否为可视化大屏请求
            "stream_text": "",        # 流式输出的累积文本（供 UI 实时刷新）
        }
        # 用闭包绑定会话ID，避免多会话并发时共享的 _ai_conv_id 被后发会话覆盖
        QTimer.singleShot(1, lambda cid=conv_id: self._execute_ai_call(cid))

    def _execute_ai_call(self, conv_id=None):
        import threading as _th
        try:
            if not conv_id:
                conv_id = getattr(self, '_ai_conv_id', None)
            state = self._conv_state.get(conv_id, {}) if conv_id else {}
            if not state:
                state = {"conv_id": conv_id, "query": (getattr(self, "_ai_user_query", "") or ""),
                    "file_ids": (getattr(self, "_ai_file_ids", []) or []),
                    "history": (getattr(self, "_ai_history", []) or []),
                    "model_key": (getattr(self, "_ai_model_key", "text_analysis") or "text_analysis"),
                    "images": (getattr(self, "_ai_images", []) or [])}
            query = state.get("query","") or ""; file_ids = state.get("file_ids",[]) or []
            history = state.get("history",[]) or []; model_key = state.get("model_key","text_analysis") or "text_analysis"
            images = state.get("images",[]) or []
            if file_ids and query:
                cached = self.db.get_cached_result(file_ids, query)
                if cached:
                    self.db.add_log("INFO","chat","cache_hit","缓存命中")
                    self._finish_ai_response(cached,conv_id); return
            cm = list(history)
            def worker(cid,st):
                try:
                    # 流式回调：把增量累积到会话状态，主线程 QTimer 轮询刷新 UI
                    def on_delta(delta):
                        if cid in self._conv_state:
                            self._conv_state[cid]["stream_text"] = \
                                self._conv_state[cid].get("stream_text", "") + delta
                    r = self.ai_service.chat(messages=cm, model_key=model_key, images=images,
                                              stream_callback=on_delta)
                    if cid in self._conv_state: self._conv_state[cid]["result"] = r or "(空)"
                except Exception as e:
                    import traceback
                    self.db.add_log("ERROR", "chat", "ai_call_fail",
                                    f"AI调用失败 [{model_key}]: {str(e)[:100]}",
                                    {"trace": traceback.format_exc()[:200]})
                    if cid in self._conv_state:
                        self._conv_state[cid]["result"] = f"⚠️ 错误: {str(e)[:200]}"
            t = _th.Thread(target=worker, args=(conv_id,state), daemon=True)
            if conv_id and conv_id in self._conv_state:
                self._conv_state[conv_id]["thread"] = t
                self._conv_state[conv_id]["start_time"] = time.time()
            t.start()
            self._poll_ai_result(conv_id)
        except Exception as e:
            self.db.add_log("ERROR","chat","execute",f"AI异常: {str(e)[:100]}")
            self._finish_ai_response(f"⚠️ 错误: {str(e)[:200]}", conv_id)

    def _poll_ai_result(self, conv_id):
        try:
            if not conv_id or conv_id not in self._conv_state: return
            st = self._conv_state[conv_id]
            thread = st.get("thread")
            if thread and thread.is_alive():
                self._update_streaming_bubble(conv_id)  # 流式输出实时刷新
                QTimer.singleShot(200, lambda: self._poll_ai_result(conv_id)); return
            result = st.get("result","") or "⚠️ 无返回"
            elapsed = int((time.time()-st.get("start_time",time.time()))*1000)
            self.db.add_log("DEBUG","chat","execute",f"AI返回 ({len(result)}字)",duration_ms=elapsed)
            # 新一轮（AI 修正后的）回复已就绪，清除上轮的 continue_requested 守卫
            st.pop("continue_requested", None)
            # 执行工具命令
            result = self._process_tool_commands(result, conv_id)
            # 若工具触发了继续推理（如大屏 spec 修正），本帧不结束，等待 AI 新一轮
            st = self._conv_state.get(conv_id, {}) or {}
            if st.get("continue_requested"):
                return
            file_ids = st.get("file_ids",[]) or []; query = st.get("query","") or ""
            if file_ids and query:
                try: self.db.save_cached_result(file_ids,query,result)
                except: pass
            self._finish_ai_response(result, conv_id)
        except Exception as e:
            import traceback
            self.db.add_log("CRITICAL", "chat", "poll_crash",
                            f"AI结果处理崩溃: {str(e)[:100]}",
                            {"trace": traceback.format_exc()[:300]})
            self.send_btn.setEnabled(True)
            self.send_btn.setText("🚀 发送")

    def _update_streaming_bubble(self, conv_id):
        """流式输出时，实时把累积文本渲染到消息区的生成中气泡"""
        try:
            st = self._conv_state.get(conv_id, {}) or {}
            lbl = st.get("label")
            text = st.get("stream_text", "")
            if lbl is None or not text:
                return
            from PyQt6.QtCore import Qt as _Qt
            from PyQt6.QtWidgets import QLabel as _QL
            lbl.setTextFormat(_Qt.TextFormat.RichText)
            lbl.setText(_md_to_html(text))
            self._scroll_to_bottom()
        except Exception:
            pass

    def _process_tool_commands(self, text, conv_id=None):
        """扫描 AI 回复中的工具命令，本地执行（conv_id 用于区分当前是哪个会话，防止多会话串线）"""
        import re, json
        # 查找 [TOOL]...[/TOOL] 标记
        pattern = r'\[TOOL\](.*?)\[/TOOL\]'
        matches = re.findall(pattern, text, re.DOTALL)
        if not matches:
            # 尝试匹配没有关闭标签的 [TOOL]（AI 可能漏了 [/TOOL]）
            orphan = re.search(r'\[TOOL\]\s*(\{.*?\})\s*(?:\n|$)', text, re.DOTALL)
            if orphan:
                block = orphan.group(1)
                matches = [block]
                text = text.replace(orphan.group(0), f"[TOOL]{block}[/TOOL]")
            else:
                # 无工具块：若是大屏请求，仍尝试把 AI 直出的 HTML 代码落成文件
                return self._dash_fallback(text, conv_id)
        for block in matches:
            try:
                try:
                    cmd = json.loads(block.strip())
                    name, args = cmd.get("name"), cmd.get("args", {})
                except json.JSONDecodeError:
                    # 非标准格式 fallback：尝试从块中提取工具名和参数
                    raw = block.strip()
                    name = None; args = {}
                    # 搜索格式: web_search("xxx") 或 search: "xxx"
                    for kw in ["web_search", "search", "fetch_url", "generate_chart", "generate_dashboard"]:
                        if kw in raw:
                            name = kw
                            import re
                            qm = re.search(r'["\']([^"\']+)["\']', raw)
                            if qm:
                                if kw in ("web_search", "search"):
                                    args["query"] = qm.group(1)
                                elif kw == "fetch_url":
                                    args["url"] = qm.group(1)
                            break
                    if not name:
                        self.db.add_log("WARNING", "chat", "tool_parse_fail",
                                        f"无法解析 [TOOL] 命令: {raw[:80]}")
                        continue

                if name == "generate_chart":
                    # 大屏请求下：把单图数据劫持转成 HTML 大屏，避免产出 PNG 图片
                    stx = self._conv_state.get(conv_id, {}) or {}
                    if stx.get("dash_request"):
                        try:
                            from core.dashboard import render_dashboard as _rd
                            _cdata = args.get("data", {}) or {}
                            _labels = _cdata.get("labels", []) or []
                            _values = _cdata.get("values", []) or []
                            if _labels and _values:
                                _m = {"bar": "bar", "line": "line", "pie": "pie", "donut": "donut",
                                      "hbar": "hbar", "area": "area", "stacked_bar": "bar"}
                                _dspec = {
                                    "title": args.get("title", "AI大屏"), "theme": "dark",
                                    "components": [{
                                        "type": _m.get(args.get("chart_type", "bar"), "bar"),
                                        "x": 0, "y": 1, "w": 24, "h": 10,
                                        "title": args.get("title", ""),
                                        "data": {"categories": _labels,
                                                 "series": [{"name": args.get("title", ""),
                                                             "data": _values}]},
                                    }],
                                }
                                _oname = f"dashboard_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
                                _opath = os.path.join(self.config.export_dir, _oname)
                                _rr = _rd(_dspec, _opath, static_dir=getattr(self.config, "static_dir", None))
                                if _rr.get("status") == "success":
                                    try:
                                        from app.database import Dashboard as _Dash2
                                        with self.db.session() as s2:
                                            _prev = s2.query(_Dash2).filter(
                                                _Dash2.conversation_id == conv_id
                                            ).order_by(_Dash2.version.desc()).first()
                                            _ver = (_prev.version + 1) if _prev else 1
                                            s2.add(_Dash2(name=_dspec["title"], spec="{}",
                                                          html_path=_opath,
                                                          file_ids=json.dumps(stx.get("file_ids", []) or [],
                                                                               ensure_ascii=False),
                                                          conversation_id=conv_id, version=_ver))
                                    except Exception:
                                        pass
                                    self._conv_state.setdefault(conv_id, {}).setdefault("gen_images", []).append(_opath)
                                    _link = ""
                                    try:
                                        from core.dashboard_server import get_global_server as _gs
                                        _srv = _gs()
                                        if not _srv.running:
                                            _srv.start(self.config.export_dir)
                                        _link = _srv.url_for(_opath)
                                    except Exception:
                                        _link = ""
                                    try:
                                        self._download_file(_opath)
                                    except Exception:
                                        pass
                                    text = text.replace(f"[TOOL]{block}[/TOOL]",
                                        f"\n🖥️ 大屏已生成\n📎 {_opath}" + (f"\n🔗 {_link}" if _link else "") + "\n")
                                    continue
                        except Exception as _e:
                            self.db.add_log("ERROR", "chat", "dash_hijack", str(_e)[:120])
                    from core.tools import generate_chart as _gc
                    args["data"] = args.get("data", {})
                    r = _gc(args["data"], args.get("chart_type","bar"), args.get("title","图表"))
                    if r.get("image_path"):
                        import shutil
                        old_path = r["image_path"]
                        new_name = f"chart_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                        new_path = os.path.join(self.config.export_dir, new_name)
                        try: shutil.copy2(old_path, new_path)
                        except: new_path = old_path
                        r["image_path"] = new_path
                        self._conv_state.setdefault(conv_id, {}).setdefault("gen_images", []).append(new_path)
                        text = text.replace(f"[TOOL]{block}[/TOOL]",
                            f"\n📊 图表已生成\n")
                    else:
                        text = text.replace(f"[TOOL]{block}[/TOOL]", f"\n⚠️ 图表生成失败\n")
                elif name == "generate_report":
                    from core.tools import generate_report as _gr
                    r = _gr(args.get("title","报告"), args.get("sources",[]), sections=args.get("sections"))
                    text = text.replace(f"[TOOL]{block}[/TOOL]",
                        f"\n📄 报告内容:\n{r.get('content','')}\n")
                elif name == "generate_ppt":
                    # 如果配置了 chart_ppt 模型，用它生成 PPT 内容
                    try:
                        from app.database import ModelConfigDB as _MC
                        with self.db.session() as s:
                            _cfg = s.query(_MC).filter(_MC.model_key == "chart_ppt", _MC.enabled == True,
                                _MC.api_key.isnot(None), _MC.api_key != "").first()
                            if _cfg:
                                import urllib.request as _ur, ssl as _ssl, json as _j, re as _re
                                _ctx = text[:2000] if text else ""
                                _ppt_conv_id = conv_id or (self.current_conversation.id if self.current_conversation else None)
                                if _ppt_conv_id:
                                    _msgs = self.db.get_messages(_ppt_conv_id, limit=5)
                                    for _m in reversed(_msgs):
                                        if _m.role == "assistant" and len(_m.content) > 100:
                                            _ctx = _m.content[:3000]
                                            break
                                _prompt = f"基于以下分析内容，生成PPT幻灯片JSON：\n{_ctx[:2000]}\n输出格式：[{{\"title\":\"页标题\",\"content\":[\"要点1\",\"要点2\"]}}]\n只输出JSON数组，3-5页，每页3-5个要点。不要markdown包裹。"
                                _body = _j.dumps({"model": _cfg.model_name or "deepseek-chat",
                                    "messages":[{"role":"user","content":_prompt}],
                                    "temperature":1,"max_tokens":8192}).encode()
                                _url = f"{(_cfg.api_base.rstrip('/') if _cfg.api_base else 'https://api.deepseek.com')}/chat/completions"
                                _headers = {"Authorization":f"Bearer {_cfg.api_key}", "Content-Type":"application/json"}
                                _ctx_ssl = _ssl.create_default_context(); _ctx_ssl.check_hostname=False; _ctx_ssl.verify_mode=_ssl.CERT_NONE
                                with _ur.urlopen(_ur.Request(_url, data=_body, headers=_headers), timeout=600, context=_ctx_ssl) as _resp:
                                    _result = _j.loads(_resp.read().decode("utf-8"))
                                _content = _result["choices"][0]["message"]["content"]
                                _clean = _content.strip()
                                if _clean.startswith("```"):
                                    _clean = _re.sub(r'^```(?:json)?\s*|\s*```$', '', _clean, flags=_re.DOTALL).strip()
                                _slides = None
                                try:
                                    _slides = _j.loads(_clean)
                                    if not isinstance(_slides, list):
                                        _slides = None
                                except Exception:
                                    pass
                                if not _slides:
                                    _match = _re.search(r'\[\s*\{.*\}\s*\]', _clean, _re.DOTALL)
                                    if _match:
                                        try:
                                            _slides = _j.loads(_match.group(0))
                                        except Exception:
                                            pass
                                if _slides and isinstance(_slides, list) and len(_slides) > 0:
                                    _slides = _j.loads(_match.group(0))
                                    if isinstance(_slides, list) and len(_slides) > 0:
                                        args["slides"] = _slides
                                        self.db.add_log("INFO","ppt","chart_ppt_ok",
                                            f"chart_ppt模型生成 {len(_slides)} 页幻灯片")
                    except Exception as _e:
                        self.db.add_log("WARNING","ppt","chart_ppt_fail", str(_e)[:80])

                    try:
                        from core.tools import generate_ppt as _gp
                    except Exception as e:
                        text = text.replace(f"[TOOL]{block}[/TOOL]",
                            f"\n⚠️ PPT生成失败: 缺少 python-pptx 库，请运行 pip install python-pptx\n")
                        continue
                    slides = args.get("slides") or []
                    if not slides and args.get("slide_titles"):
                        slides = [{"title": t, "content": []} for t in args["slide_titles"]]
                    r = _gp(args.get("title","PPT"), slides, slide_count=args.get("slide_count"))
                    fp = r.get("file_path","")
                    if fp and os.path.exists(fp):
                        import shutil
                        new_name = f"ppt_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pptx"
                        new_path = os.path.join(self.config.export_dir, new_name)
                        shutil.copy2(fp, new_path)
                        fp = new_path
                        self._conv_state.setdefault(conv_id, {}).setdefault("gen_images", []).append(fp)
                        text = text.replace(f"[TOOL]{block}[/TOOL]",
                            f"\n📽️ PPT已生成\n")
                    else:
                        err = r.get("error", "未知错误")
                        text = text.replace(f"[TOOL]{block}[/TOOL]",
                            f"\n⚠️ PPT生成失败: {err}\n")
                elif name == "generate_dashboard":
                    from core.dashboard import (validate_spec, render_dashboard,
                                                extract_structured_data, build_data_preview)
                    spec = args.get("spec") or args.get("dashboard") or args
                    if isinstance(spec, dict):
                        if isinstance(spec.get("spec"), dict):
                            spec = spec["spec"]
                        elif isinstance(spec.get("dashboard"), dict):
                            spec = spec["dashboard"]
                    if not isinstance(spec, dict):
                        spec = {}
                    # 取当前会话选中的表格文件（用会话状态，不用全局 selector，防多会话串线）
                    st = self._conv_state.get(conv_id, {}) or {}
                    tab_file = None
                    try:
                        from app.database import File as _F
                        for fid in (st.get("file_ids", []) or []):
                            with self.db.session() as s:
                                f = s.query(_F).filter(_F.id == fid).first()
                            if f and f.file_type in ("xlsx", "csv"):
                                tab_file = f
                                break
                    except Exception:
                        tab_file = None
                    preview = ""
                    if tab_file:
                        try:
                            sd = extract_structured_data(tab_file.storage_path, tab_file.file_type)
                            preview = build_data_preview(sd)
                        except Exception:
                            preview = ""
                    errors = validate_spec(spec) if spec else ["spec 缺失"]
                    if errors:
                        rc = st.get("retry_count", 0)
                        if rc >= 2 or st.get("continue_requested"):
                            text = text.replace(f"[TOOL]{block}[/TOOL]",
                                f"\n⚠️ 大屏 spec 校验失败: {'; '.join(errors[:3])}\n"
                                "（AI 已尝试修正，若仍失败请换个说法重试）\n")
                        else:
                            self._finish_tool_and_continue(
                                "大屏 spec 校验失败，请修正后重新输出完整 spec：\n"
                                + "\n".join(errors[:10])
                                + ("\n[数据预览]\n" + preview if preview
                                   else "\n（未找到 xlsx/csv 表格文件，请提示用户先选择）"),
                                conv_id)
                            st["retry_count"] = rc + 1
                            st["continue_requested"] = True
                            text = text.replace(f"[TOOL]{block}[/TOOL]", "\n（大屏生成中，AI 正在修正 spec...）")
                        continue
                    # 渲染 HTML 大屏
                    try:
                        out_name = f"dashboard_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
                        out_path = os.path.join(self.config.export_dir, out_name)
                        r = render_dashboard(spec, out_path,
                                             static_dir=getattr(self.config, "static_dir", None))
                        if r.get("status") == "success":
                            # 落库（会话内版本递增）
                            try:
                                from app.database import Dashboard as _Dash
                                with self.db.session() as s:
                                    prev = s.query(_Dash).filter(
                                        _Dash.conversation_id == conv_id
                                    ).order_by(_Dash.version.desc()).first()
                                    ver = (prev.version + 1) if prev else 1
                                    s.add(_Dash(name=spec.get("title", "AI可视化大屏"),
                                                spec=json.dumps(spec, ensure_ascii=False),
                                                html_path=out_path,
                                                file_ids=json.dumps(st.get("file_ids", []) or [],
                                                                     ensure_ascii=False),
                                                conversation_id=conv_id, version=ver))
                            except Exception:
                                pass
                            self._conv_state.setdefault(conv_id, {}).setdefault("gen_images", []).append(out_path)
                            # 本地 http 链接 + 浏览器打开
                            link = ""
                            try:
                                from core.dashboard_server import get_global_server
                                server = get_global_server()
                                if not server.running:
                                    server.start(self.config.export_dir)
                                link = server.url_for(out_path)
                            except Exception:
                                link = ""
                            try:
                                self._download_file(out_path)
                            except Exception:
                                pass
                            repl = f"\n🖥️ 大屏已生成\n📎 {out_path}"
                            if link:
                                repl += f"\n🔗 {link}"
                            text = text.replace(f"[TOOL]{block}[/TOOL]", repl + "\n")
                        else:
                            rc = st.get("retry_count", 0)
                            if rc >= 2 or st.get("continue_requested"):
                                text = text.replace(f"[TOOL]{block}[/TOOL]",
                                    f"\n⚠️ 大屏渲染失败: {str(r.get('errors', [])[:1])}\n")
                            else:
                                self._finish_tool_and_continue(
                                    f"大屏渲染失败: {r.get('errors')}\n{preview}", conv_id)
                                st["retry_count"] = rc + 1
                                st["continue_requested"] = True
                                text = text.replace(f"[TOOL]{block}[/TOOL]", "\n（大屏渲染出错，正在重试...）")
                    except Exception as e:
                        self.db.add_log("ERROR", "chat", "dashboard_fail", str(e)[:150])
                        text = text.replace(f"[TOOL]{block}[/TOOL]",
                            f"\n⚠️ 大屏生成失败: {str(e)[:100]}\n")
                elif name == "web_search":
                    query = args.get("query", "")
                    if query:
                        result_text = "暂无结果"
                        try:
                            import urllib.request as _ur, urllib.parse as _up, re as _re
                            url = "https://cn.bing.com/search?q=" + _up.quote(query) + "&count=10"
                            req = _ur.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"})
                            with _ur.urlopen(req, timeout=15) as r:
                                html = r.read().decode("utf-8", errors="replace")
                            items, seen = [], set()
                            # Bing 搜索结果在 <li class="b_algo"> 里
                            blocks = _re.findall(r'<li class="b_algo"[^>]*>(.*?)</li>', html, _re.DOTALL)
                            for block in blocks:
                                title_m = _re.search(r'<a[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>', block)
                                snippet_m = _re.search(r'<p[^>]*>(.*?)</p>', block, _re.DOTALL)
                                if title_m:
                                    link = title_m.group(1)
                                    title = _re.sub(r'<[^>]+>', '', title_m.group(2)).strip()
                                    snippet = _re.sub(r'<[^>]+>', '', snippet_m.group(1)).strip()[:200] if snippet_m else ""
                                    if "bing" not in link and link not in seen and title:
                                        seen.add(link)
                                        items.append(f"{title}\n{link}\n{snippet}")
                            result_text = "\n\n".join(items[:8]) if items else "未找到结果"
                        except Exception as e:
                            result_text = f"搜索失败: {str(e)[:60]}"
                        text = text.replace("[TOOL]" + block + "[/TOOL]", "\n🔍 搜索结果 (" + query + "):\n" + result_text + "\n")
                elif name == "fetch_url":
                    url = args.get("url", "")
                    if url:
                        try:
                            import urllib.request as _ur
                            with _ur.urlopen(url, timeout=15) as resp:
                                html = resp.read().decode("utf-8", errors="replace")[:5000]
                            import re
                            text_content = re.sub(r'<[^>]+>', '', html)
                            text_content = re.sub(r'\s+', ' ', text_content).strip()[:2000]
                            text = text.replace(f"[TOOL]{block}[/TOOL]",
                                f"\n🌐 网页内容 ({url}):\n{text_content}\n")
                        except Exception as e:
                            text = text.replace(f"[TOOL]{block}[/TOOL]",
                                f"\n⚠️ 抓取失败: {str(e)[:100]}\n")
                    else:
                        text = text.replace(f"[TOOL]{block}[/TOOL]", "\n⚠️ 缺少URL\n")
                elif name in ("list_workspace_files", "list_files", "scan_files", "list_knowledge_base"):
                    # 扫描知识库文件
                    try:
                        file_list = []
                        # 只统计当前选择的资源
                        kb_id = self.kb_selector.currentData()
                        folder_id = self.folder_selector.currentData()
                        sel_file_id = self.file_selector.currentData()
                        if sel_file_id:
                            from app.database import File as _F
                            with self.db.session() as s:
                                f = s.query(_F).filter(_F.id == sel_file_id).first()
                                if f: file_list = [(f.original_name, f.file_type, f.status)]
                        elif folder_id:
                            files = self.db.list_files(folder_id)
                            file_list = [(f.original_name, f.file_type, f.status) for f in files]
                        elif kb_id:
                            files = self.db.list_files_by_knowledge_base(kb_id)
                            file_list = [(f.original_name, f.file_type, f.status) for f in files]
                        if file_list:
                            result = "\n".join(f"- {n} ({t}, {s})" for n, t, s in file_list[:50])
                            text = text.replace(f"[TOOL]{block}[/TOOL]",
                                f"\n📁 共 {len(file_list)} 个文件:\n{result}\n")
                        else:
                            text = text.replace(f"[TOOL]{block}[/TOOL]",
                                "\n📁 当前没有选择知识库或知识库为空。\n")
                    except Exception as e:
                        text = text.replace(f"[TOOL]{block}[/TOOL]",
                            f"\n⚠️ 扫描文件失败: {str(e)[:60]}\n")
                else:
                    # 未知工具：返回友好提示
                    self.db.add_log("WARNING", "chat", "unknown_tool",
                                    f"未知工具: {name}", detail={"args": str(args)[:100]})
                    text = text.replace(f"[TOOL]{block}[/TOOL]",
                        f"\n⚠️ 我不支持「{name}」这个操作，请换一种方式描述你的需求。\n")
            except Exception as e:
                import traceback
                err = str(e)[:100]
                self.db.add_log("ERROR", "chat", "tool_crash",
                                f"工具执行失败 [{name if 'name' in dir() else '?'}]: {err}",
                                {"trace": traceback.format_exc()[:200]})
                text = text.replace(f"[TOOL]{block}[/TOOL]",
                    f"\n⚠️ 操作失败: {err}\n")

        return self._dash_fallback(text, conv_id)

    def _dash_fallback(self, text, conv_id=None):
        """HTML 兜底：AI 直接输出 HTML 代码（没走工具）时，识别并保存成文件+链接"""
        st = self._conv_state.get(conv_id, {}) or {}
        if not st.get("dash_request"):
            return text
        try:
            code, raw_match = _extract_html_code(text)
            if code and raw_match:
                out_name = f"dashboard_ai_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
                out_path = os.path.join(self.config.export_dir, out_name)
                os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(code)
                try:
                    from app.database import Dashboard as _Dash
                    with self.db.session() as s:
                        prev = s.query(_Dash).filter(
                            _Dash.conversation_id == conv_id
                        ).order_by(_Dash.version.desc()).first()
                        ver = (prev.version + 1) if prev else 1
                        s.add(_Dash(name="AI直出大屏", spec="{}", html_path=out_path,
                                    file_ids=json.dumps(st.get("file_ids", []) or [],
                                                         ensure_ascii=False),
                                    conversation_id=conv_id, version=ver))
                except Exception:
                    pass
                self._conv_state.setdefault(conv_id, {}).setdefault("gen_images", []).append(out_path)
                link = ""
                try:
                    from core.dashboard_server import get_global_server
                    server = get_global_server()
                    if not server.running:
                        server.start(self.config.export_dir)
                    link = server.url_for(out_path)
                except Exception:
                    link = ""
                try:
                    self._download_file(out_path)
                except Exception:
                    pass
                repl = f"\n🖥️ 大屏已生成\n📎 {out_path}"
                if link:
                    repl += f"\n🔗 {link}"
                text = text.replace(raw_match, repl + "\n")
        except Exception as e:
            self.db.add_log("ERROR", "chat", "dashboard_fallback", str(e)[:150])
        return text

    def _finish_tool_and_continue(self, tool_result_text, conv_id):
        """工具执行后，把结果反馈给 AI 继续推理"""
        try:
            if not conv_id or conv_id not in self._conv_state:
                self._finish_ai_response(tool_result_text, conv_id)
                return

            st = self._conv_state[conv_id]
            history = st.get("history", []) or []

            # 先把带工具结果的 AI 回复加入历史
            history.append({"role": "assistant", "content": tool_result_text})

            # 加一条 system 消息通知 AI 工具已执行，请继续
            history.append({
                "role": "user",
                "content": "工具已执行完成，结果是上面 assistant 消息中的内容。"
                           "根据这些结果继续你的回答。如果还需要其他工具，"
                           "请再次使用 [TOOL] 命令。如果已经得到答案，请直接给出最终回复。"
            })

            model_key = st.get("model_key", "text_analysis")
            cm = list(history)

            # 后台调用 AI 继续
            import threading as _th

            def continue_worker(cid, msgs, mk):
                try:
                    r = self.ai_service.chat(messages=msgs, model_key=mk)
                    if cid in self._conv_state:
                        self._conv_state[cid]["result"] = r or "(空)"
                except Exception as e:
                    import traceback
                    self.db.add_log("ERROR", "chat", "continue_fail",
                                    f"AI继续推理失败: {str(e)[:100]}")
                    if cid in self._conv_state:
                        self._conv_state[cid]["result"] = f"\n⚠️ 继续推理时出错: {str(e)[:200]}"

            t = _th.Thread(target=continue_worker, args=(conv_id, cm, model_key), daemon=True)
            if conv_id in self._conv_state:
                self._conv_state[conv_id]["thread"] = t
                self._conv_state[conv_id]["start_time"] = time.time()
            t.start()

            # 轮询继续的结果
            self._poll_ai_result(conv_id)

        except Exception as e:
            self.db.add_log("ERROR", "chat", "continue_crash",
                            f"工具继续流程崩溃: {str(e)[:100]}")
            self._finish_ai_response(tool_result_text, conv_id)

    def _finish_ai_response(self, result, conv_id=None):
        if conv_id and self._response_done.get(conv_id, False): return
        if conv_id: self._response_done[conv_id] = True
        try:
            # 清理思考标签
            lbl = None
            if conv_id and conv_id in self._conv_state:
                lbl = self._conv_state[conv_id].get("label")
            else:
                lbl = getattr(self, '_ai_label', None)
            if lbl:
                try: lbl.deleteLater()
                except: pass
            # 确定 conv_id
            if not conv_id:
                conv_id = getattr(self, '_ai_conv_id', None)
            if not conv_id:
                return
            # 取出会话状态（在 pop 之前保留引用，供后续读取）
            st = self._conv_state.get(conv_id, {}) or {}
            # 本会话生成的图片/文件（按会话隔离；仅单会话时兼容旧全局列表）
            images = st.get("gen_images", []) or []
            if not images and len(self._responding_convs) <= 1:
                images = getattr(self, '_ai_generated_images', []) or []
            images = list(dict.fromkeys(images))
            img_files = [p for p in images if p.lower().endswith(('.png','.jpg','.jpeg','.gif'))]
            doc_files = [p for p in images if not p.lower().endswith(('.png','.jpg','.jpeg','.gif'))]

            # ── 无论当前展示的是哪个会话，都先把 AI 回复落库，保证回复不丢失 ──
            meta = {}
            if img_files: meta["images"] = img_files
            if doc_files: meta["files"] = doc_files
            try:
                self.db.add_message(conv_id, "assistant", result, metadata=meta if meta else None)
            except Exception as e:
                self.db.add_log("ERROR", "chat", "save_msg_fail", str(e)[:100])

            # 清理响应状态（防止 _load_messages 重新添加思考标签）
            if conv_id in self._responding_convs:
                self._responding_convs.pop(conv_id, None)
            if conv_id in self._conv_state:
                self._conv_state.pop(conv_id, None)

            is_current = self.current_conversation and self.current_conversation.id == conv_id
            if is_current:
                # ── 当前会话 → 刷新界面并写分析记录 ──
                self._load_conversations(select_id=conv_id)
                for img_path in img_files:
                    try:
                        from PyQt6.QtGui import QPixmap
                        pix = QPixmap(img_path)
                        if not pix.isNull():
                            il = QLabel()
                            il.setPixmap(pix.scaledToWidth(560))
                            il.setStyleSheet("padding:4px 0")
                            self.messages_layout.addWidget(il)
                    except: pass
                try:
                    fn = st.get("file_names", []) or []
                    fid = st.get("file_ids", []) or []
                    if not fn and not fid:
                        fn = getattr(self, '_ai_file_names', []) or []
                        fid = getattr(self, '_ai_file_ids', []) or []
                    s = result[:100].replace("\n", " ") + ("..." if len(result) > 100 else "")
                    gen_files = (img_files or []) + (doc_files or [])
                    all_sources = (fn or fid or []) + gen_files
                    # 自动把分析结果导出为可读的 .md 文件，用户可直接用记事本打开查看
                    try:
                        from datetime import datetime as _dt
                        md_name = f"分析记录_{_dt.now().strftime('%Y%m%d_%H%M%S')}.md"
                        md_path = os.path.join(self.config.export_dir, md_name)
                        with open(md_path, "w", encoding="utf-8") as mf:
                            mf.write(f"# {self.current_conversation.title or 'AI对话'}\n\n"
                                     f"生成时间: {_dt.now().strftime('%Y-%m-%d %H:%M')}\n\n---\n\n{result}")
                        gen_files = gen_files + [md_path]
                        all_sources = all_sources + [md_path]
                    except Exception:
                        pass
                    self.db.create_analysis_record(title=self.current_conversation.title or "AI对话",
                        analysis_type="chat", content=result, summary=s, conversation_id=conv_id,
                        source_files=all_sources if all_sources else None)
                except Exception as e:
                    self.db.add_log("WARNING", "chat", "record_fail",
                                    f"分析记录写入失败: {str(e)[:80]}")
            else:
                # ── 非当前会话完成 → 刷新会话列表里的消息数，让用户能看到新回复 ──
                try:
                    self._update_conversation_count(conv_id)
                except Exception:
                    pass
        except Exception as e:
            self.db.add_log("ERROR", "chat", "finish_ui_error", str(e)[:100])
        try:
            if conv_id and conv_id in self._responding_convs:
                self._responding_convs.pop(conv_id, None)
            # 清理会话状态
            if conv_id and conv_id in self._conv_state:
                self._conv_state.pop(conv_id, None)
            # 发送按钮状态跟随当前会话，而不是无条件恢复
            self._update_send_btn()
            self._ai_history = None; self._ai_label = None
        except: pass

    def _update_conversation_count(self, conv_id):
        try:
            for i in range(self.conv_list.count()):
                item = self.conv_list.item(i)
                if item and item.data(Qt.ItemDataRole.UserRole) == conv_id:
                    conv = self.db.get_conversation(conv_id)
                    if conv:
                        w = self.conv_list.itemWidget(item)
                        if w:
                            labels = w.findChildren(QLabel)
                            if labels:
                                title = conv.title if len(conv.title) <= 20 else conv.title[:20] + "..."
                                cnt = conv.message_count or 0
                                prefix = "📌" if conv.is_pinned else "💬"
                                labels[0].setText(f"{prefix} {title}  ({cnt}条)")
                    break
        except: pass

    def on_activate(self):
        cid = self.current_conversation.id if self.current_conversation else None
        self._load_conversations(select_id=cid)
        self._load_kb_selector()
        self._update_send_btn()
