"""
智汇中枢 - 数据库管理模块
SQLite + SQLAlchemy 实现
"""

import os
import json
import hashlib
from datetime import datetime, timedelta
from contextlib import contextmanager
from typing import Optional

from sqlalchemy import (
    create_engine, Column, Integer, String, Text, DateTime,
    Float, Boolean, ForeignKey, JSON, Index, func, event
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

Base = declarative_base()


# ═══════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════

class KnowledgeBase(Base):
    """知识库"""
    __tablename__ = "knowledge_bases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    icon = Column(String(50), default="📂")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime, nullable=True)

    folders = relationship("Folder", back_populates="knowledge_base",
                           cascade="all, delete-orphan")


class Folder(Base):
    """文件夹"""
    __tablename__ = "folders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    knowledge_base_id = Column(Integer, ForeignKey("knowledge_bases.id"), nullable=False)
    name = Column(String(200), nullable=False)
    parent_id = Column(Integer, ForeignKey("folders.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime, nullable=True)

    knowledge_base = relationship("KnowledgeBase", back_populates="folders")
    parent = relationship("Folder", remote_side=[id], backref="children")
    files = relationship("File", back_populates="folder", cascade="all, delete-orphan")


class File(Base):
    """文件"""
    __tablename__ = "files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    folder_id = Column(Integer, ForeignKey("folders.id"), nullable=False)
    original_name = Column(String(500), nullable=False)
    storage_path = Column(String(1000), nullable=False)
    file_type = Column(String(20), nullable=False)  # pdf, docx, xlsx, img, txt...
    file_size = Column(Integer, default=0)  # bytes
    md5_hash = Column(String(64), default="")
    status = Column(String(20), default="pending")
    # pending, parsed, parsing_failed, quality_low, oversized
    quality_score = Column(Float, nullable=True)  # 0-100
    content_text = Column(Text, nullable=True)  # 解析后的文本
    page_count = Column(Integer, default=0)
    tags = Column(Text, default="[]")  # JSON 数组
    chunk_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime, nullable=True)

    folder = relationship("Folder", back_populates="files")
    chunks = relationship("FileChunk", back_populates="file", cascade="all, delete-orphan")

    def get_tags(self) -> list:
        return json.loads(self.tags) if self.tags else []

    def set_tags(self, tags: list):
        self.tags = json.dumps(tags, ensure_ascii=False)

    # 同 Conversation：防止回收站彻底清理后新文件复用旧 id
    __table_args__ = {"sqlite_autoincrement": True}


class FileChunk(Base):
    """文件分块"""
    __tablename__ = "file_chunks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(Integer, ForeignKey("files.id"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    char_count = Column(Integer, default=0)
    embedding_id = Column(String(100), nullable=True)  # 向量ID

    file = relationship("File", back_populates="chunks")

    __table_args__ = (
        Index("idx_file_chunk", "file_id", "chunk_index"),
    )


class Conversation(Base):
    """会话"""
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(500), default="新会话")
    knowledge_base_id = Column(Integer, nullable=True)
    folder_id = Column(Integer, nullable=True)
    file_id = Column(Integer, nullable=True)
    model_mode = Column(String(20), default="auto")  # auto | manual
    manual_model = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    message_count = Column(Integer, default=0)
    is_pinned = Column(Boolean, default=False)
    tags = Column(Text, default="[]")  # JSON 数组

    messages = relationship("Message", back_populates="conversation",
                            cascade="all, delete-orphan",
                            order_by="Message.created_at")

    # sqlite_autoincrement：禁止删除后复用行 id（否则新会话会"继承"旧会话的 id，
    # 连带查出旧会话遗留的消息）
    __table_args__ = {"sqlite_autoincrement": True}


class Message(Base):
    """消息"""
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)
    role = Column(String(20), nullable=False)  # user | assistant | system
    content = Column(Text, nullable=False)
    content_type = Column(String(20), default="text")
    # text | chart | report | ppt | file
    msg_metadata = Column(Text, default="{}")  # JSON 额外信息
    feedback = Column(Integer, nullable=True)  # 1=赞, -1=踩
    feedback_reason = Column(String(200), nullable=True)
    token_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)

    conversation = relationship("Conversation", back_populates="messages")

    __table_args__ = (
        Index("idx_conv_msgs", "conversation_id", "created_at"),
    )


class AnalysisRecord(Base):
    """分析记录"""
    __tablename__ = "analysis_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(500), default="分析记录")
    analysis_type = Column(String(50), default="")  # query, analysis, chart, report, ppt, export
    content = Column(Text, default="")  # JSON 格式的完整结果
    summary = Column(Text, default="")  # 简要摘要
    source_files = Column(Text, default="[]")  # 涉及的文件ID列表
    conversation_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime, nullable=True)


class RecycleBin(Base):
    """回收站"""
    __tablename__ = "recycle_bin"

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_type = Column(String(20), nullable=False)  # knowledge_base, folder, file, analysis
    item_id = Column(Integer, nullable=False)
    item_name = Column(String(500), default="")
    deleted_at = Column(DateTime, default=datetime.now)
    expires_at = Column(DateTime, nullable=False)


class SystemLog(Base):
    """系统日志"""
    __tablename__ = "system_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    level = Column(String(10), default="INFO")  # DEBUG, INFO, WARNING, ERROR
    module = Column(String(50), default="system")  # file, ai_engine, api, user
    action = Column(String(100), default="")
    message = Column(Text, default="")
    detail = Column(Text, default="{}")  # JSON 详情
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_log_time", "created_at"),
        Index("idx_log_level", "level"),
    )


class ModelConfigDB(Base):
    """模型配置（持久化）"""
    __tablename__ = "model_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_key = Column(String(100), unique=True, nullable=False)
    name = Column(String(200), default="")
    api_key = Column(String(500), default="")
    api_base = Column(String(500), default="")
    model_name = Column(String(200), default="")
    enabled = Column(Boolean, default=False)
    connect_timeout = Column(Integer, default=30)
    max_retries = Column(Integer, default=3)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class AnalysisCache(Base):
    """分析缓存（文件+查询 → AI 结果）"""
    __tablename__ = "analysis_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_ids_hash = Column(String(64), nullable=False, index=True)  # 多个文件ID排序后拼接的MD5
    query_hash = Column(String(64), nullable=False, index=True)     # 用户问题的MD5
    query_text = Column(Text, default="")
    result = Column(Text, default="")
    chunk_count = Column(Integer, default=1)
    token_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)
    accessed_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class Dashboard(Base):
    """AI 可视化大屏（每版一条记录）"""
    __tablename__ = "dashboards"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), default="AI可视化大屏")
    spec = Column(Text, nullable=False)          # 完整 spec JSON 文本
    html_path = Column(String(1000), default="")  # 生成的 HTML 文件绝对路径
    file_ids = Column(Text, default="[]")        # JSON 数组，来源文件ID
    conversation_id = Column(Integer, nullable=True, index=True)
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


# ═══════════════════════════════════════
# 数据库管理器
# ═══════════════════════════════════════

class DatabaseManager:
    """数据库管理器"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.engine = create_engine(f"sqlite:///{db_path}?check_same_thread=False",
                                    echo=False)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)
        # SQLite 默认 journal 模式下写操作锁全库，多会话并发写（后台AI线程+主线程）
        # 会互相阻塞甚至报 database is locked。开启 WAL + busy_timeout 解决。
        @event.listens_for(self.engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, conn_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    def initialize(self):
        """初始化数据库，创建表"""
        Base.metadata.create_all(self.engine)
        self._cleanup_orphans()

    def _cleanup_orphans(self):
        """清理孤儿数据（历史 bug 遗留）：
        1. 消息指向已不存在的会话（删除会话时未级联删消息，SQLite 复用会话 id
           后新会话会"继承"这些旧消息，表现为删除会话后新建会话出现历史对话）
        2. 文件分块指向已不存在的文件
        """
        try:
            with self.session() as s:
                s.query(Message).filter(
                    ~Message.conversation_id.in_(s.query(Conversation.id))
                ).delete(synchronize_session=False)
                s.query(FileChunk).filter(
                    ~FileChunk.file_id.in_(s.query(File.id))
                ).delete(synchronize_session=False)
        except Exception:
            pass

    @contextmanager
    def session(self):
        """获取数据库会话"""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ─── 知识库操作 ───

    def _abs_storage_path(self, storage_path: str) -> str:
        """把 storage_path 规范为绝对路径（相对路径基于项目根目录）"""
        if not storage_path:
            return ""
        if os.path.isabs(storage_path):
            return storage_path
        return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", storage_path))

    def _remove_file_from_disk(self, storage_path: str):
        """按记录的真实路径删除磁盘文件"""
        p = self._abs_storage_path(storage_path)
        if p and os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass

    def _cleanup_kb_upload_dirs(self, kb_names: set):
        """删除 uploads 下该知识库对应的目录。
        优先按名字匹配（原名 + 上传时用的安全名），再自底向上清理空目录。"""
        try:
            import shutil
            upload_dir = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "data", "uploads"))
            if not os.path.exists(upload_dir):
                return
            for name in kb_names:
                if not name:
                    continue
                safe_name = "".join(c for c in name if c.isalnum() or c in " _-")
                for d in {os.path.join(upload_dir, name),
                          os.path.join(upload_dir, safe_name)}:
                    if os.path.isdir(d):
                        try:
                            shutil.rmtree(d)
                        except Exception:
                            pass
            # 自底向上清理残留的空目录（文件已按记录删干净后，文件夹级目录变空）
            for root, dirs, _files in os.walk(upload_dir, topdown=False):
                for d in dirs:
                    dp = os.path.join(root, d)
                    try:
                        os.rmdir(dp)
                    except OSError:
                        pass
        except Exception:
            pass

    def create_knowledge_base(self, name: str, description: str = "") -> KnowledgeBase:
        with self.session() as s:
            kb = KnowledgeBase(name=name, description=description)
            s.add(kb)
            s.flush()
            # 创建默认文件夹
            default_folder = Folder(knowledge_base_id=kb.id, name="默认文件夹")
            s.add(default_folder)
            return kb

    def list_knowledge_bases(self):
        with self.session() as s:
            return s.query(KnowledgeBase).filter(
                KnowledgeBase.is_deleted == False
            ).order_by(KnowledgeBase.updated_at.desc()).all()

    def get_knowledge_base(self, kb_id: int):
        with self.session() as s:
            return s.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()

    def delete_knowledge_base(self, kb_id: int):
        """删除知识库：软删除 DB 记录（进回收站），并按每个文件的 storage_path
        逐个删除磁盘文件，最后清理 uploads 下对应目录，保证库与文件夹同步"""
        storage_paths = []
        kb_names = set()
        with self.session() as s:
            kb = s.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
            if not kb:
                return
            kb_names.add(kb.name)

            # 级联软删除所有层级的文件夹和文件
            folders = s.query(Folder).filter(
                Folder.knowledge_base_id == kb_id
            ).all()
            for folder in folders:
                if not folder.is_deleted:
                    folder.is_deleted = True
                    folder.deleted_at = datetime.now()
                    s.add(RecycleBin(
                        item_type="folder", item_id=folder.id,
                        item_name=folder.name,
                        expires_at=datetime.now() + timedelta(days=30)
                    ))
                # 收集该文件夹下全部文件的物理路径（含历史已软删的，磁盘一并清理）
                files = s.query(File).filter(File.folder_id == folder.id).all()
                for f in files:
                    if f.storage_path:
                        storage_paths.append(f.storage_path)
                    if not f.is_deleted:
                        f.is_deleted = True
                        f.deleted_at = datetime.now()
                        s.add(RecycleBin(
                            item_type="file", item_id=f.id,
                            item_name=f.original_name,
                            expires_at=datetime.now() + timedelta(days=30)
                        ))

            # 添加到回收站
            s.add(RecycleBin(
                item_type="knowledge_base",
                item_id=kb.id,
                item_name=kb.name,
                expires_at=datetime.now() + timedelta(days=30)
            ))
            kb.is_deleted = True
            kb.deleted_at = datetime.now()

        # 事务提交后再删物理文件，避免事务回滚但文件已删
        for p in storage_paths:
            self._remove_file_from_disk(p)
        self._cleanup_kb_upload_dirs(kb_names)

    # ─── 文件夹操作 ───

    def create_folder(self, kb_id: int, name: str, parent_id: int = None) -> Folder:
        with self.session() as s:
            folder = Folder(knowledge_base_id=kb_id, name=name, parent_id=parent_id)
            s.add(folder)
            return folder

    def list_folders(self, kb_id: int, parent_id: int = None):
        with self.session() as s:
            query = s.query(Folder).filter(
                Folder.knowledge_base_id == kb_id,
                Folder.is_deleted == False
            )
            if parent_id is None:
                query = query.filter(Folder.parent_id == None)
            else:
                query = query.filter(Folder.parent_id == parent_id)
            return query.order_by(Folder.name).all()

    # ─── 文件操作 ───

    def create_file(self, folder_id: int, original_name: str, storage_path: str,
                    file_type: str, file_size: int = 0, md5_hash: str = "") -> File:
        with self.session() as s:
            file = File(
                folder_id=folder_id,
                original_name=original_name,
                storage_path=storage_path,
                file_type=file_type,
                file_size=file_size,
                md5_hash=md5_hash,
                status="pending"
            )
            s.add(file)
            s.flush()
            # 更新文件夹的更新时间
            folder = s.query(Folder).filter(Folder.id == folder_id).first()
            if folder:
                folder.updated_at = datetime.now()
            return file

    def list_files(self, folder_id: int):
        with self.session() as s:
            return s.query(File).filter(
                File.folder_id == folder_id,
                File.is_deleted == False
            ).order_by(File.updated_at.desc()).all()

    def list_files_by_knowledge_base(self, kb_id: int):
        """列出知识库下的所有文件（跨文件夹）"""
        from app.database import Folder
        with self.session() as s:
            return s.query(File).join(Folder).filter(
                Folder.knowledge_base_id == kb_id,
                File.is_deleted == False,
                Folder.is_deleted == False,
            ).order_by(File.updated_at.desc()).all()

    def search_files(self, keyword: str, kb_id: int = None):
        """搜索文件"""
        with self.session() as s:
            query = s.query(File).filter(File.is_deleted == False)
            if keyword:
                query = query.filter(
                    File.original_name.contains(keyword) |
                    File.content_text.contains(keyword)
                )
            if kb_id:
                query = query.join(Folder).filter(Folder.knowledge_base_id == kb_id)
            return query.limit(50).all()

    def update_file_status(self, file_id: int, status: str, quality_score: float = None,
                           content_text: str = None, chunk_count: int = None):
        with self.session() as s:
            file = s.query(File).filter(File.id == file_id).first()
            if file:
                file.status = status
                if quality_score is not None:
                    file.quality_score = quality_score
                if content_text is not None:
                    file.content_text = content_text
                if chunk_count is not None:
                    file.chunk_count = chunk_count

    def delete_file(self, file_id: int):
        storage_path = ""
        with self.session() as s:
            file = s.query(File).filter(File.id == file_id).first()
            if file:
                storage_path = file.storage_path or ""
                file.is_deleted = True
                file.deleted_at = datetime.now()
                s.add(RecycleBin(
                    item_type="file",
                    item_id=file.id,
                    item_name=file.original_name,
                    expires_at=datetime.now() + timedelta(days=30)
                ))
        # 事务提交后再删除物理文件，保证库与磁盘同步
        if storage_path:
            self._remove_file_from_disk(storage_path)

    def delete_folder(self, folder_id: int):
        """删除文件夹：递归软删除所有子文件夹及文件，并同步删除物理文件"""
        storage_paths = []
        with self.session() as s:
            folder = s.query(Folder).filter(Folder.id == folder_id).first()
            if not folder:
                return
            # 递归收集所有后代文件夹 id（不限层级，避免子文件夹残留导致
            # 其文件仍被选中发给 AI）
            all_folder_ids = []
            stack = [folder_id]
            while stack:
                fid = stack.pop()
                if fid in all_folder_ids:
                    continue
                all_folder_ids.append(fid)
                children = s.query(Folder.id).filter(Folder.parent_id == fid).all()
                stack.extend(cid for (cid,) in children)
            for fid in all_folder_ids:
                f_obj = s.query(Folder).filter(Folder.id == fid).first()
                if f_obj and not f_obj.is_deleted:
                    f_obj.is_deleted = True
                    f_obj.deleted_at = datetime.now()
                    s.add(RecycleBin(
                        item_type="folder", item_id=f_obj.id,
                        item_name=f_obj.name,
                        expires_at=datetime.now() + timedelta(days=30)
                    ))
                files = s.query(File).filter(File.folder_id == fid).all()
                for f in files:
                    if f.storage_path:
                        storage_paths.append(f.storage_path)
                    if not f.is_deleted:
                        f.is_deleted = True
                        f.deleted_at = datetime.now()
                        s.add(RecycleBin(
                            item_type="file", item_id=f.id,
                            item_name=f.original_name,
                            expires_at=datetime.now() + timedelta(days=30)
                        ))
        # 事务提交后统一删除物理文件
        for p in storage_paths:
            self._remove_file_from_disk(p)
        self._cleanup_kb_upload_dirs(set())

    # ─── 文件分块操作 ───

    def save_chunks(self, file_id: int, chunks: list[str]):
        with self.session() as s:
            for i, content in enumerate(chunks):
                chunk = FileChunk(
                    file_id=file_id,
                    chunk_index=i,
                    content=content,
                    char_count=len(content)
                )
                s.add(chunk)
            file = s.query(File).filter(File.id == file_id).first()
            if file:
                file.chunk_count = len(chunks)

    def get_chunks(self, file_id: int):
        with self.session() as s:
            return s.query(FileChunk).filter(
                FileChunk.file_id == file_id
            ).order_by(FileChunk.chunk_index).all()

    # ─── 会话操作 ───

    def create_conversation(self, title: str = "新会话") -> Conversation:
        with self.session() as s:
            conv = Conversation(title=title)
            s.add(conv)
            return conv

    def list_conversations(self):
        with self.session() as s:
            return s.query(Conversation).order_by(
                Conversation.is_pinned.desc(),
                Conversation.updated_at.desc()
            ).limit(100).all()

    def get_conversation(self, conv_id: int):
        with self.session() as s:
            return s.query(Conversation).filter(Conversation.id == conv_id).first()

    def delete_conversation(self, conv_id: int) -> bool:
        """彻底删除会话：必须连同其全部消息一起删除。
        注意不能用 bulk delete 直接删 conversations 行——ORM 的级联删除只对
        session.delete(obj) 生效；而且 SQLite 删除最大 id 行后新行会复用该 id，
        遗留的消息会被新会话"继承"（表现为新建会话出现历史对话记录）。"""
        with self.session() as s:
            conv = s.query(Conversation).filter(Conversation.id == conv_id).first()
            if not conv:
                return False
            s.query(Message).filter(
                Message.conversation_id == conv_id
            ).delete(synchronize_session=False)
            s.delete(conv)
            return True

    def add_message(self, conv_id: int, role: str, content: str,
                    content_type: str = "text", metadata: dict = None,
                    token_count: int = 0) -> Message:
        with self.session() as s:
            msg = Message(
                conversation_id=conv_id,
                role=role,
                content=content,
                content_type=content_type,
                msg_metadata=json.dumps(metadata or {}, ensure_ascii=False),
                token_count=token_count
            )
            s.add(msg)
            conv = s.query(Conversation).filter(Conversation.id == conv_id).first()
            if conv:
                conv.message_count = s.query(Message).filter(
                    Message.conversation_id == conv_id
                ).count()
                conv.updated_at = datetime.now()
            return msg

    def get_messages(self, conv_id: int, limit: int = 100):
        """取最近 limit 条消息（按时间正序返回）。
        原实现直接正序 limit，多轮对话后发给 AI 的永远是最早的消息。"""
        with self.session() as s:
            msgs = s.query(Message).filter(
                Message.conversation_id == conv_id
            ).order_by(Message.created_at.desc(), Message.id.desc()).limit(limit).all()
            return list(reversed(msgs))

    def set_message_feedback(self, msg_id: int, feedback: int, reason: str = None):
        with self.session() as s:
            msg = s.query(Message).filter(Message.id == msg_id).first()
            if msg:
                msg.feedback = feedback
                msg.feedback_reason = reason

    # ─── 分析记录操作 ───

    def create_analysis_record(self, title: str, analysis_type: str,
                               content: str, summary: str = "",
                               source_files: list = None, conversation_id: int = None):
        with self.session() as s:
            record = AnalysisRecord(
                title=title,
                analysis_type=analysis_type,
                content=content,
                summary=summary,
                source_files=json.dumps(source_files or [], ensure_ascii=False),
                conversation_id=conversation_id
            )
            s.add(record)
            return record

    def list_analysis_records(self):
        with self.session() as s:
            return s.query(AnalysisRecord).filter(
                AnalysisRecord.is_deleted == False
            ).order_by(AnalysisRecord.created_at.desc()).limit(200).all()

    # ─── 大屏操作 ───

    def create_dashboard(self, name, spec, html_path, file_ids=None,
                         conversation_id=None, version=None) -> Dashboard:
        """新建大屏版本，version 缺省时按会话自动递增"""
        with self.session() as s:
            if version is None:
                prev = s.query(Dashboard).filter(
                    Dashboard.conversation_id == conversation_id
                ).order_by(Dashboard.version.desc()).first()
                version = (prev.version + 1) if prev else 1
            d = Dashboard(name=name, spec=spec, html_path=html_path,
                          file_ids=json.dumps(file_ids or [], ensure_ascii=False),
                          conversation_id=conversation_id, version=version)
            s.add(d)
            return d

    def get_latest_dashboard(self, conversation_id) -> Optional[Dashboard]:
        with self.session() as s:
            return s.query(Dashboard).filter(
                Dashboard.conversation_id == conversation_id
            ).order_by(Dashboard.version.desc()).first()

    def list_dashboards(self, conversation_id=None, limit=50):
        with self.session() as s:
            q = s.query(Dashboard)
            if conversation_id:
                q = q.filter(Dashboard.conversation_id == conversation_id)
            return q.order_by(Dashboard.updated_at.desc()).limit(limit).all()

    def get_dashboard(self, dashboard_id) -> Optional[Dashboard]:
        with self.session() as s:
            return s.query(Dashboard).filter(Dashboard.id == dashboard_id).first()

    # ─── 回收站操作 ───

    def list_recycle_bin(self):
        with self.session() as s:
            return s.query(RecycleBin).order_by(RecycleBin.deleted_at.desc()).all()

    def restore_item(self, rb_id: int):
        with self.session() as s:
            rb = s.query(RecycleBin).filter(RecycleBin.id == rb_id).first()
            if not rb:
                return
            if rb.item_type == "knowledge_base":
                item = s.query(KnowledgeBase).filter(KnowledgeBase.id == rb.item_id).first()
                if item:
                    item.is_deleted = False
                    item.deleted_at = None
                    # 恢复所有关联的文件和文件夹
                    folders = s.query(Folder).filter(
                        Folder.knowledge_base_id == rb.item_id,
                        Folder.is_deleted == True
                    ).all()
                    for folder in folders:
                        folder.is_deleted = False
                        folder.deleted_at = None
                    files = s.query(File).join(Folder).filter(
                        Folder.knowledge_base_id == rb.item_id,
                        File.is_deleted == True
                    ).all()
                    for f in files:
                        f.is_deleted = False
                        f.deleted_at = None
                    # 清理对应的回收站记录
                    s.query(RecycleBin).filter(
                        RecycleBin.item_type.in_(["folder", "file"]),
                        RecycleBin.item_id.in_(
                            [f.id for f in folders] +
                            [f.id for f in files]
                        )
                    ).delete(synchronize_session=False)
            elif rb.item_type == "folder":
                item = s.query(Folder).filter(Folder.id == rb.item_id).first()
                if item:
                    item.is_deleted = False
                    item.deleted_at = None
            elif rb.item_type == "file":
                item = s.query(File).filter(File.id == rb.item_id).first()
                if item:
                    item.is_deleted = False
                    item.deleted_at = None
            elif rb.item_type == "analysis":
                item = s.query(AnalysisRecord).filter(AnalysisRecord.id == rb.item_id).first()
                if item:
                    item.is_deleted = False
                    item.deleted_at = None
            s.delete(rb)

    def clean_expired_items(self):
        """清理过期回收站项目（连带物理文件和分块记录，不留死数据）"""
        file_paths = []
        with self.session() as s:
            now = datetime.now()
            expired = s.query(RecycleBin).filter(RecycleBin.expires_at <= now).all()
            for rb in expired:
                if rb.item_type == "knowledge_base":
                    s.query(KnowledgeBase).filter(
                        KnowledgeBase.id == rb.item_id
                    ).delete()
                elif rb.item_type == "file":
                    f = s.query(File).filter(File.id == rb.item_id).first()
                    if f and f.storage_path:
                        file_paths.append(f.storage_path)
                    s.query(FileChunk).filter(
                        FileChunk.file_id == rb.item_id
                    ).delete(synchronize_session=False)
                    s.query(File).filter(File.id == rb.item_id).delete()
                elif rb.item_type == "analysis":
                    s.query(AnalysisRecord).filter(
                        AnalysisRecord.id == rb.item_id
                    ).delete()
                s.delete(rb)
        for p in file_paths:
            self._remove_file_from_disk(p)

    # ─── 日志操作 ───

    def add_log(self, level: str, module: str, action: str,
                message: str, detail: dict = None, duration_ms: int = None):
        with self.session() as s:
            log = SystemLog(
                level=level,
                module=module,
                action=action,
                message=message,
                detail=json.dumps(detail or {}, ensure_ascii=False),
                duration_ms=duration_ms
            )
            s.add(log)

    def query_logs(self, level: str = None, module: str = None,
                   start_time: datetime = None, end_time: datetime = None,
                   limit: int = 50):
        with self.session() as s:
            query = s.query(SystemLog)
            if level:
                query = query.filter(SystemLog.level == level)
            if module:
                query = query.filter(SystemLog.module == module)
            if start_time:
                query = query.filter(SystemLog.created_at >= start_time)
            if end_time:
                query = query.filter(SystemLog.created_at <= end_time)
            return query.order_by(SystemLog.created_at.desc()).limit(limit).all()

    def query_logs_advanced(self, level: str = None, module: str = None,
                            search_text: str = None,
                            start_time: datetime = None, end_time: datetime = None,
                            limit: int = 200, offset: int = 0):
        """高级日志查询，支持搜索文本"""
        with self.session() as s:
            query = s.query(SystemLog)
            if level:
                query = query.filter(SystemLog.level == level)
            if module:
                query = query.filter(SystemLog.module == module)
            if search_text:
                like = f"%{search_text}%"
                query = query.filter(
                    SystemLog.message.ilike(like) |
                    SystemLog.action.ilike(like) |
                    SystemLog.detail.ilike(like)
                )
            if start_time:
                query = query.filter(SystemLog.created_at >= start_time)
            if end_time:
                query = query.filter(SystemLog.created_at <= end_time)
            return query.order_by(SystemLog.created_at.desc()).offset(offset).limit(limit).all()

    def get_log_stats(self, start_time: datetime = None, end_time: datetime = None):
        """获取日志统计：各级别数量"""
        from sqlalchemy import func
        with self.session() as s:
            query = s.query(SystemLog.level, func.count(SystemLog.id))
            if start_time:
                query = query.filter(SystemLog.created_at >= start_time)
            if end_time:
                query = query.filter(SystemLog.created_at <= end_time)
            results = query.group_by(SystemLog.level).all()
        stats = {"DEBUG": 0, "INFO": 0, "WARNING": 0, "ERROR": 0}
        for level, count in results:
            stats[level] = count
        stats["TOTAL"] = sum(stats.values())
        return stats

    def get_distinct_modules(self):
        """获取所有出现过的模块名"""
        with self.session() as s:
            results = s.query(SystemLog.module).distinct().all()
        return sorted([r[0] for r in results if r[0]])

    # ─── 缓存操作（版本 v2: 改内容限制后递增版本号，自动失效旧缓存）───
    CACHE_VERSION = "v4"

    def _make_cache_key(self, file_ids: list, query: str) -> tuple:
        """生成缓存键：版本 + 文件ID哈希 + 查询哈希"""
        ids_str = ",".join(str(i) for i in sorted(file_ids))
        file_hash = hashlib.md5(ids_str.encode()).hexdigest()
        query_hash = hashlib.md5(query.encode()).hexdigest()
        # 版本号确保改内容限制后旧缓存自动失效
        return f"{self.CACHE_VERSION}_{file_hash}", f"{self.CACHE_VERSION}_{query_hash}"

    def get_cached_result(self, file_ids: list, query: str) -> Optional[str]:
        """查询缓存：相同文件+相同问题，直接返回之前的结果"""
        file_hash, query_hash = self._make_cache_key(file_ids, query)
        with self.session() as s:
            cached = s.query(AnalysisCache).filter(
                AnalysisCache.file_ids_hash == file_hash,
                AnalysisCache.query_hash == query_hash
            ).first()
            if cached:
                cached.accessed_at = datetime.now()
                return cached.result
        return None

    def save_cached_result(self, file_ids: list, query: str, result: str,
                           chunk_count: int = 1, token_count: int = 0):
        """保存分析结果到缓存"""
        file_hash, query_hash = self._make_cache_key(file_ids, query)
        with self.session() as s:
            existing = s.query(AnalysisCache).filter(
                AnalysisCache.file_ids_hash == file_hash,
                AnalysisCache.query_hash == query_hash
            ).first()
            if existing:
                existing.result = result
                existing.chunk_count = chunk_count
                existing.token_count = token_count
                existing.accessed_at = datetime.now()
            else:
                s.add(AnalysisCache(
                    file_ids_hash=file_hash,
                    query_hash=query_hash,
                    query_text=query[:200],
                    result=result,
                    chunk_count=chunk_count,
                    token_count=token_count
                ))
