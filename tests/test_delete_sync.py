# -*- coding: utf-8 -*-
"""测试三个修复点：会话删除级联、知识库/文件删除与磁盘同步、文件夹递归删除"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import DatabaseManager, Conversation, Message, KnowledgeBase, Folder, File, FileChunk

PASSED = []
FAILED = []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print(f"  [通过] {name}")
    else:
        FAILED.append(name)
        print(f"  [失败] {name} {detail}")


def test_conversation_delete_cascade():
    """① 删除会话后新建会话不出现历史记录"""
    print("\n== 测试1：删除会话级联删除消息 ==")
    # ignore_cleanup_errors: Windows 下 SQLite 连接池持有文件句柄，目录清理失败不影响断言
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        db = DatabaseManager(os.path.join(td, "t.db"))
        db.initialize()

        conv = db.create_conversation("会话A")
        cid = conv.id
        db.add_message(cid, "user", "问题1")
        db.add_message(cid, "assistant", "回答1")
        check("删除前有消息", len(db.get_messages(cid)) == 2)

        ok = db.delete_conversation(cid)
        check("delete_conversation 返回 True", ok is True)

        # 消息必须被级联删除
        with db.session() as s:
            left = s.query(Message).filter(Message.conversation_id == cid).count()
        check("消息已级联删除", left == 0, f"残留 {left} 条")

        # 新会话若复用同一 id，不得继承旧消息
        conv2 = db.create_conversation("新会话")
        msgs = db.get_messages(conv2.id)
        check("新建会话无历史记录", len(msgs) == 0, f"查到 {len(msgs)} 条旧消息")
        check("再删一次返回 False", db.delete_conversation(cid) is False)


def test_orphan_cleanup():
    """② 历史遗留的孤儿消息在启动时被清理"""
    print("\n== 测试2：孤儿消息启动清理 ==")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        db = DatabaseManager(os.path.join(td, "t.db"))
        db.initialize()
        # 模拟历史 bug：直接插入指向不存在会话的消息
        with db.session() as s:
            s.add(Message(conversation_id=999, role="user", content="孤儿消息"))
        db2 = DatabaseManager(os.path.join(td, "t.db"))
        db2.initialize()  # 启动清理
        with db2.session() as s:
            left = s.query(Message).filter(Message.conversation_id == 999).count()
        check("孤儿消息已清理", left == 0, f"残留 {left} 条")


def test_kb_delete_disk_sync():
    """③ 删除知识库时磁盘文件同步删除"""
    print("\n== 测试3：知识库删除与磁盘同步 ==")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        # uploads 目录按项目结构放在 data/ 下
        data_dir = os.path.join(td, "data")
        upload_dir = os.path.join(data_dir, "uploads", "测试库", "默认文件夹")
        os.makedirs(upload_dir)
        for i in range(3):
            with open(os.path.join(upload_dir, f"f{i}.txt"), "w") as f:
                f.write(f"内容{i}")

        db = DatabaseManager(os.path.join(data_dir, "t.db"))
        db.initialize()
        kb = db.create_knowledge_base("测试库")
        folder = db.list_folders(kb.id)[0]
        paths = []
        for i in range(3):
            p = os.path.join(upload_dir, f"f{i}.txt")
            db.create_file(folder.id, f"f{i}.txt", p, "txt", 10)
            paths.append(p)

        db.delete_knowledge_base(kb.id)

        check("DB 中知识库已软删", db.list_knowledge_bases() == [])
        check("物理文件已删除", all(not os.path.exists(p) for p in paths),
              f"残留 {[p for p in paths if os.path.exists(p)]}")
        check("uploads 下目录已清理", not os.path.exists(
            os.path.join(data_dir, "uploads", "测试库")))

        # 重命名场景：KB 改名后目录还是旧名，删除时也要清干净
        kb2 = db.create_knowledge_base("原名库")
        f2 = db.list_folders(kb2.id)[0]
        old_dir = os.path.join(data_dir, "uploads", "原名库", "默认文件夹")
        os.makedirs(old_dir, exist_ok=True)
        p2 = os.path.join(old_dir, "x.txt")
        with open(p2, "w") as fh:
            fh.write("x")
        db.create_file(f2.id, "x.txt", p2, "txt", 1)
        # 改名（目录名不变）
        with db.session() as s:
            k = s.query(KnowledgeBase).filter(KnowledgeBase.id == kb2.id).first()
            k.name = "改名后的库"
        db.delete_knowledge_base(kb2.id)
        check("重命名后删除仍清磁盘", not os.path.exists(p2))


def test_folder_recursive_delete():
    """④ 删除文件夹递归处理子文件夹"""
    print("\n== 测试4：文件夹递归删除 ==")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        db = DatabaseManager(os.path.join(td, "t.db"))
        db.initialize()
        kb = db.create_knowledge_base("库")
        parent = db.list_folders(kb.id)[0]
        child = db.create_folder(kb.id, "子文件夹", parent_id=parent.id)
        p_parent = os.path.join(td, "a.txt")
        p_child = os.path.join(td, "b.txt")
        for p in (p_parent, p_child):
            with open(p, "w") as f:
                f.write("x")
        db.create_file(parent.id, "a.txt", p_parent, "txt", 1)
        db.create_file(child.id, "b.txt", p_child, "txt", 1)

        db.delete_folder(parent.id)

        with db.session() as s:
            c = s.query(File).filter(File.id != None, File.is_deleted == False).count()
            f_del = s.query(Folder).filter(Folder.id == child.id, Folder.is_deleted == False).count()
        check("父文件夹文件已软删+物理删", c == 0 and not os.path.exists(p_parent))
        check("子文件夹递归软删", f_del == 0)
        check("子文件夹文件物理删除", not os.path.exists(p_child))


def test_file_delete():
    """⑤ 删除单个文件物理同步"""
    print("\n== 测试5：单个文件删除 ==")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        db = DatabaseManager(os.path.join(td, "t.db"))
        db.initialize()
        kb = db.create_knowledge_base("库")
        folder = db.list_folders(kb.id)[0]
        p = os.path.join(td, "f.txt")
        with open(p, "w") as f:
            f.write("内容")
        rec = db.create_file(folder.id, "f.txt", p, "txt", 2)
        db.delete_file(rec.id)
        check("物理文件已删除", not os.path.exists(p))
        # 删除不存在的文件 id 不应崩溃
        try:
            db.delete_file(99999)
            check("删除不存在id不崩溃", True)
        except Exception as e:
            check("删除不存在id不崩溃", False, str(e))


def test_get_messages_recent():
    """⑥ get_messages 取最近 N 条"""
    print("\n== 测试6：历史消息取最近N条 ==")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        db = DatabaseManager(os.path.join(td, "t.db"))
        db.initialize()
        conv = db.create_conversation("c")
        for i in range(10):
            db.add_message(conv.id, "user", f"消息{i}")
        msgs = db.get_messages(conv.id, limit=3)
        check("取到3条", len(msgs) == 3)
        check("是最近3条且正序", [m.content for m in msgs] == ["消息7", "消息8", "消息9"],
              f"实际 {[m.content for m in msgs]}")


if __name__ == "__main__":
    test_conversation_delete_cascade()
    test_orphan_cleanup()
    test_kb_delete_disk_sync()
    test_folder_recursive_delete()
    test_file_delete()
    test_get_messages_recent()
    print(f"\n结果：{len(PASSED)} 通过, {len(FAILED)} 失败")
    sys.exit(1 if FAILED else 0)
