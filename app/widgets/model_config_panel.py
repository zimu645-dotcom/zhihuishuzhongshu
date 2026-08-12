"""
智汇中枢 - 大模型配置面板
支持多模型独立配置、连接测试、能力健康检查
"""

import json
import threading

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame,
    QLineEdit, QFormLayout, QGroupBox, QMessageBox,
    QTextEdit, QTabWidget, QInputDialog, QSpinBox,
    QAbstractItemView, QCheckBox, QComboBox
)
from PyQt6.QtCore import Qt, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QBrush

from core.ai_service import AIService


class ModelConfigPanel(QWidget):
    """大模型配置面板"""

    # 测试结果信号（后台线程安全通知主线程）
    test_result = pyqtSignal(int, object, bool, str)

    # 预定义能力项：(key, 显示名, 默认模型名)
    CAPABILITIES = [
        ("text_analysis", "文本分析与推理", "deepseek-chat"),
        ("chart_ppt", "图表/PPT制作", "deepseek-chat"),
        ("vision", "图片识别/PDF版面理解", "gpt-4o"),
    ]

    def __init__(self, config, db, main_window):
        super().__init__()
        self.config = config
        self.db = db
        self.main_window = main_window
        self.ai_service = AIService(db)
        self._test_results = {}
        self._selected_models = {}  # key -> 用户选择的模型名（不受数据库影响）
        self._init_ui()
        self._load_config()
        # 连接测试结果信号（线程安全）
        self.test_result.connect(self._on_test_result)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # 顶部标题
        title = QLabel("⚙️ 大模型配置")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        hint = QLabel("为每项能力独立配置模型。系统将根据任务类型自动调度对应模型。")
        hint.setStyleSheet("color: #888; font-size: 13px; padding-bottom: 8px;")
        layout.addWidget(hint)

        # 配置表格
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "能力项", "API地址", "模型名称", "API密钥", "状态"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 260)
        self.table.setColumnWidth(2, 220)
        self.table.setColumnWidth(3, 260)
        self.table.setColumnWidth(4, 90)
        self.table.setStyleSheet("""
            QTableWidget::item { padding: 6px 10px; }
            QTableWidget { border: 1px solid #e8e8e8; border-radius: 8px; }
            QHeaderView::section { padding: 8px; font-weight: bold; }
        """)
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.verticalHeader().setVisible(False)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)

        layout.addWidget(self.table, 1)

        # 操作按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        self.test_all_btn = QPushButton("  🧪  全部测试连接")
        self.test_all_btn.setObjectName("primaryButton")
        self.test_all_btn.clicked.connect(self._on_test_all)
        btn_layout.addWidget(self.test_all_btn)

        self.save_btn = QPushButton("  💾  保存配置")
        self.save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(self.save_btn)

        self.export_btn = QPushButton("  📤  导出配置文件")
        self.export_btn.setToolTip("把当前所有模型配置导出成一份可读的文本文件（记事本可直接打开）")
        self.export_btn.clicked.connect(self._on_export_config)
        btn_layout.addWidget(self.export_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def _load_config(self):
        """从数据库加载配置"""
        self.table.setRowCount(len(self.CAPABILITIES))

        db_configs = {}
        with self.db.session() as s:
            from app.database import ModelConfigDB
            configs = s.query(ModelConfigDB).all()
            for cfg in configs:
                db_configs[cfg.model_key] = cfg

        for row, (key, name, default_model_name) in enumerate(self.CAPABILITIES):
            cfg_enabled = True
            if key in db_configs:
                cfg_enabled = db_configs[key].enabled
            status_icon = "🟢" if cfg_enabled else "🔴"
            name_item = QTableWidgetItem(f"{status_icon} {name}")
            name_item.setData(Qt.ItemDataRole.UserRole, key)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            name_item.setToolTip("双击切换启用/禁用")
            self.table.setItem(row, 0, name_item)

            api_base_val = ""
            model_name_val = ""
            api_key_val = ""

            if key in db_configs:
                cfg = db_configs[key]
                api_base_val = cfg.api_base or ""
                model_name_val = cfg.model_name or ""
                api_key_val = cfg.api_key or ""
                key_item = QTableWidgetItem(api_key_val)
                if cfg.api_key:
                    key_item.setToolTip("完整密钥已保存，可直接使用")
            else:
                key_item = QTableWidgetItem("")

            self.table.setItem(row, 1, QTableWidgetItem(api_base_val))

            # 模型名称：使用输入框，用户可自由填写
            model_edit = QLineEdit(model_name_val)
            model_edit.setPlaceholderText("如 deepseek-chat, gpt-4o, gemini-pro...")
            model_edit.setStyleSheet("QLineEdit{border:1px solid #d9d9d9;border-radius:4px;padding:4px 6px;background:white} QLineEdit:focus{border-color:#1a73e8}")
            model_edit.textChanged.connect(lambda t, k=key: self._selected_models.update({k: t}))
            self.table.setCellWidget(row, 2, model_edit)

            self.table.setItem(row, 3, key_item)

            if key in self._test_results:
                status_text, status_color = self._test_results[key]
                status_item = QTableWidgetItem(status_text)
                status_item.setForeground(QColor(status_color))
            else:
                status_item = QTableWidgetItem("未测试")
                status_item.setForeground(QColor("#faad14"))
            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 4, status_item)

    def _get_current_configs(self) -> list:
        configs = []
        for row in range(self.table.rowCount()):
            key = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            configs.append({
                "key": key,
                "name": self.table.item(row, 0).text(),
                "api_base": self.table.item(row, 1).text() if self.table.item(row, 1) else "",
                "model_name": self.table.item(row, 2).text() if self.table.item(row, 2) else "",
                "api_key": self.table.item(row, 3).text() if self.table.item(row, 3) else "",
            })
        return configs

    def _on_cell_double_clicked(self, row, col):
        """双击能力项切换启用/禁用"""
        if col == 0:
            try:
                item = self.table.item(row, 0)
                if not item: return
                key = item.data(Qt.ItemDataRole.UserRole)
                text = item.text()
                if text.startswith("🟢"):
                    item.setText(text.replace("🟢", "🔴"))
                elif text.startswith("🔴"):
                    item.setText(text.replace("🔴", "🟢"))
                self._on_save()
                self.db.add_log("INFO", "config", "toggle", f"切换 {key} 状态")
            except Exception:
                pass

    def _on_test_all(self):
        try:
            self._on_save()
            for row in range(self.table.rowCount()):
                self._test_single_row(row)
        except Exception:
            pass

    def _test_single_row(self, row):
        try:
            key = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            api_key = self.table.item(row, 3).text() if self.table.item(row, 3) else ""
            if not api_key:
                item = QTableWidgetItem("⏸️ 未配置")
                item.setForeground(QColor("#faad14"))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, 4, item)
                self._test_results[key] = ("⏸️ 未配置", "#faad14")
                return

            self._on_save()

            import urllib.request as _ur, urllib.error as _ue, ssl as _ssl, json as _j

            def do_test():
                try:
                    cfg = self.ai_service.get_model_config(key)
                    if not cfg:
                        self.test_result.emit(row, key, False, "未找到配置")
                        return
                    model_name = cfg.get("model_name", "deepseek-chat")
                    url = f"{cfg['api_base'].rstrip('/')}/chat/completions"
                    body = _j.dumps({"model": model_name, "messages": [{"role": "user", "content": "OK"}], "max_tokens": 5}).encode()
                    ctx = _ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = _ssl.CERT_NONE
                    req = _ur.Request(url, data=body, headers={"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"}, method="POST")
                    with _ur.urlopen(req, timeout=15, context=ctx) as r:
                        _j.loads(r.read())
                    self.test_result.emit(row, key, True, "")
                except _ue.HTTPError as e:
                    b = ""
                    try: b = e.read().decode("utf-8", errors="replace")[:80]
                    except: pass
                    self.test_result.emit(row, key, False, f"HTTP {e.code}")
                except _ue.URLError as e:
                    self.test_result.emit(row, key, False, f"网络: {str(e.reason)[:60]}")
                except Exception as e:
                    self.test_result.emit(row, key, False, str(e)[:60])

            threading.Thread(target=do_test, daemon=True).start()
        except Exception:
            pass

    def _on_test_result(self, row, key, success, msg=""):
        try:
            if success:
                txt = "✅ 连接成功"
                color = "#34a853"
            else:
                txt = f"❌ {msg}" if msg else "❌ 连接失败"
                color = "#ea4335"
            item = QTableWidgetItem(txt)
            item.setForeground(QColor(color))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 4, item)
            self._test_results[key] = (txt, color)
            if not success and msg:
                self.db.add_log("WARNING", "config", "test_fail", f"{key}: {msg}")
        except:
            pass

    def _on_export_config(self):
        """把当前模型配置导出成可读的 JSON 文件（用户可直接用记事本打开查看）"""
        try:
            import os
            from datetime import datetime
            rows = []
            for row in range(self.table.rowCount()):
                key = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
                api_base = self.table.item(row, 1).text() if self.table.item(row, 1) else ""
                model_edit = self.table.cellWidget(row, 2)
                model_name = model_edit.text() if (model_edit is not None and hasattr(model_edit, "text")) else ""
                api_key = self.table.item(row, 3).text() if self.table.item(row, 3) else ""
                name_text = self.table.item(row, 0).text() if self.table.item(row, 0) else ""
                rows.append({
                    "能力": name_text,
                    "API地址": api_base,
                    "模型名称": model_name,
                    "API密钥": api_key,
                    "启用": name_text.startswith("🟢"),
                })
            export = {
                "说明": "这是智汇中枢的大模型配置备份文件，可直接用记事本打开查看。",
                "导出时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "模型配置": rows,
            }
            out_dir = os.path.join(self.config.export_dir, "model_configs")
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(out_dir, f"model配置_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(export, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "导出成功",
                                    f"已导出到:\n{path}\n\n（这是普通文本文件，双击用记事本打开即可查看，不用碰数据库）")
            self.db.add_log("INFO", "config", "export", "导出模型配置")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def _on_save(self):
        """保存配置"""
        try:
            with self.db.session() as s:
                from app.database import ModelConfigDB
                for row in range(self.table.rowCount()):
                    key = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
                    api_base = self.table.item(row, 1).text() if self.table.item(row, 1) else ""
                    model_edit = self.table.cellWidget(row, 2)
                    if isinstance(model_edit, QLineEdit):
                        model_name = model_edit.text()
                    elif key in self._selected_models:
                        model_name = self._selected_models[key]
                    else:
                        model_name = self.table.item(row, 2).text() if self.table.item(row, 2) else ""
                    api_key = self.table.item(row, 3).text() if self.table.item(row, 3) else ""

                    cfg = s.query(ModelConfigDB).filter(
                        ModelConfigDB.model_key == key).first()
                    if not cfg:
                        cfg = ModelConfigDB(model_key=key)
                        s.add(cfg)
                    cfg.api_base = api_base
                    cfg.model_name = model_name
                    cfg.api_key = api_key
                    name_text = self.table.item(row, 0).text() if self.table.item(row, 0) else ""
                    cfg.enabled = name_text.startswith("🟢")

            QMessageBox.information(self, "保存成功", "配置已保存")
            self.db.add_log("INFO", "config", "save", "保存模型配置")
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))

    def on_activate(self):
        """页面激活时刷新"""
        self._load_config()
