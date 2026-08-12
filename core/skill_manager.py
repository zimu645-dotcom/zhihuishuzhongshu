"""
智汇中枢 - 技能管理器
管理 .skill 文件的安装、卸载、加载
"""

import os
import json
import zipfile
import shutil
from datetime import datetime
from typing import Optional, Callable


SKILL_DIR = None  # 由 initialize 设置

# 内置技能（系统自带，不可卸载）
BUILTIN_SKILLS = {}


def initialize(data_dir: str):
    """初始化技能目录"""
    global SKILL_DIR
    SKILL_DIR = os.path.join(data_dir, "skills")
    os.makedirs(SKILL_DIR, exist_ok=True)
    _create_builtin()


def _create_builtin():
    """创建内置技能文件"""
    skills = {
        "数据整理": {
            "name": "数据整理",
            "version": "1.0.0",
            "description": "合并表格、清洗数据、生成汇总报告",
            "author": "系统内置",
            "prompt": "当用户要求整理数据时，从知识库读取表格文件，进行合并、清洗，生成汇总报告。"
        },
        "网页抓取": {
            "name": "网页抓取",
            "version": "1.0.0",
            "description": "获取网页内容、提取关键信息",
            "author": "系统内置",
            "prompt": "当用户要求获取网页内容时，直接抓取用户提供的网址并提取关键信息回答。"
        },
        "联网搜索": {
            "name": "联网搜索",
            "version": "1.0.0",
            "description": "搜索互联网获取最新信息",
            "author": "系统内置",
            "prompt": "当用户需要最新信息时，搜索互联网并基于搜索结果给出精确答案，包含具体数字和日期。"
        },
    }
    for name, info in skills.items():
        skill_dir = os.path.join(SKILL_DIR, f"{name}.skill")
        if not os.path.exists(skill_dir):
            os.makedirs(skill_dir, exist_ok=True)
            info_path = os.path.join(skill_dir, "skill.json")
            with open(info_path, "w", encoding="utf-8") as f:
                json.dump(info, f, ensure_ascii=False, indent=2)
            BUILTIN_SKILLS[name] = True


def list_skills() -> list:
    """列出所有已安装的技能"""
    skills = []
    if not SKILL_DIR or not os.path.exists(SKILL_DIR):
        return skills
    for name in sorted(os.listdir(SKILL_DIR)):
        skill_dir = os.path.join(SKILL_DIR, name)
        if not os.path.isdir(skill_dir):
            continue
        info_path = os.path.join(skill_dir, "skill.json")
        if os.path.exists(info_path):
            with open(info_path, "r", encoding="utf-8") as f:
                info = json.load(f)
            info["dir"] = skill_dir
            info["builtin"] = name.replace(".skill", "") in BUILTIN_SKILLS
            info["enabled"] = info.get("enabled", True)
            skills.append(info)
    return skills


def get_enabled_prompts() -> str:
    """获取所有启用技能的提示词"""
    prompts = []
    for skill in list_skills():
        if skill.get("enabled") and skill.get("prompt"):
            prompts.append(skill["prompt"])
    return "\n".join(prompts)


def install_skill(zip_path: str, db_log: Callable = None) -> tuple:
    """从 zip 文件安装技能"""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            skill_json = None
            for n in names:
                if n.endswith("skill.json"):
                    skill_json = n
                    break
            if not skill_json:
                return False, "无效的技能包：未找到 skill.json"
            info = json.loads(zf.read(skill_json))
            skill_name = info.get("name", "未命名技能")
            skill_dir = os.path.join(SKILL_DIR, f"{skill_name}.skill")
            if os.path.exists(skill_dir):
                backup = skill_dir + ".bak"
                if os.path.exists(backup):
                    shutil.rmtree(backup)
                shutil.copytree(skill_dir, backup)
            zf.extractall(skill_dir)
            if db_log:
                db_log("INFO", "skill", "install", f"安装技能: {skill_name}")
            return True, f"✅ 技能「{skill_name}」安装成功"
    except Exception as e:
        return False, f"❌ 安装失败: {str(e)[:100]}"


def uninstall_skill(skill_name: str, db_log: Callable = None) -> tuple:
    """卸载技能"""
    skill_dir = os.path.join(SKILL_DIR, f"{skill_name}.skill")
    if not os.path.exists(skill_dir):
        return False, "技能不存在"
    if skill_name in BUILTIN_SKILLS:
        return False, "内置技能不能卸载"
    try:
        shutil.rmtree(skill_dir)
        if db_log:
            db_log("INFO", "skill", "uninstall", f"卸载技能: {skill_name}")
        return True, f"✅ 技能「{skill_name}」已卸载"
    except Exception as e:
        return False, f"❌ 卸载失败: {str(e)[:100]}"


def toggle_skill(skill_name: str, enabled: bool, db_log: Callable = None) -> tuple:
    """启用/禁用技能"""
    skill_dir = os.path.join(SKILL_DIR, f"{skill_name}.skill")
    info_path = os.path.join(skill_dir, "skill.json")
    if not os.path.exists(info_path):
        return False, "技能不存在"
    try:
        with open(info_path, "r", encoding="utf-8") as f:
            info = json.load(f)
        info["enabled"] = enabled
        with open(info_path, "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False, indent=2)
        status = "启用" if enabled else "禁用"
        if db_log:
            db_log("INFO", "skill", "toggle", f"{status}技能: {skill_name}")
        return True, f"✅ 技能「{skill_name}」已{status}"
    except Exception as e:
        return False, f"❌ 操作失败: {str(e)[:100]}"


def export_skill(skill_name: str, export_dir: str) -> Optional[str]:
    """导出技能为 zip 包"""
    skill_dir = os.path.join(SKILL_DIR, f"{skill_name}.skill")
    if not os.path.exists(skill_dir):
        return None
    zip_path = os.path.join(export_dir, f"{skill_name}.skill.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(skill_dir):
            for f in files:
                file_path = os.path.join(root, f)
                arcname = os.path.relpath(file_path, skill_dir)
                zf.write(file_path, arcname)
    return zip_path
