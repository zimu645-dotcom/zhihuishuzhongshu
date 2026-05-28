# 智汇中枢 (ZhihuiZhongshu)

智能知识工作台 — AI 驱动的本地知识管理与数据分析桌面应用。

## 功能

- 💬 **智能对话** — 基于大模型（DeepSeek/Kimi/GPT 等）的自然语言交互
- 📚 **知识库管理** — 上传文件自动解析，知识库→文件夹→文件三级管理
- 🔍 **联网搜索** — 内置 Bing 搜索，AI 可自动联网获取最新信息
- 📊 **图表生成** — 柱状图/折线图/饼图/雷达图等 12+ 种图表类型
- 📄 **报告生成** — 自动生成结构化分析报告
- 📽️ **PPT 制作** — 基于分析结果一键生成演示文稿（支持 5 种设计主题）
- 🧩 **技能系统** — 可扩展的 AI 技能，增强智能体能力
- 🔄 **文件实时同步** — 上传文件夹与知识库双向实时同步
- 🗑️ **回收站** — 误删可恢复

## 系统要求

| 平台 | 支持 |
|------|------|
| macOS 11+ | ✅ |
| Windows 10/11 | ✅ |

## 快速开始

### 方式一：直接运行源码

#### macOS

```bash
# 1. 克隆项目
git clone https://github.com/your-username/zhihuishuzhongshu.git
cd zhihuishuzhongshu

# 2. 运行启动脚本（自动创建虚拟环境并安装依赖）
chmod +x setup_mac.command
./setup_mac.command
```

或者手动执行：

```bash
cd zhihuishuzhongshu
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

#### Windows

```bash
# 1. 克隆或下载项目
# 2. 双击 setup_windows.bat（自动创建虚拟环境、安装依赖、启动应用）
```

或者手动执行：

```bash
cd zhihuishuzhongshu
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

### 方式二：打包为独立应用

在 Windows 上运行 `setup_windows.bat`，会自动打包生成 `dist/ZhihuiZhongshu.exe`（约 200MB），可直接复制到其他 Windows 电脑运行，无需安装 Python。

## 首次使用配置

1. 启动应用后，进入 **大模型配置** 页面
2. 填写 API 地址和密钥（推荐 DeepSeek：`https://api.deepseek.com`）
3. 点击 **测试连接** 验证配置
4. 点击 **保存配置**
5. 开始对话或上传文件到知识库

### 获取 API 密钥

- [DeepSeek](https://platform.deepseek.com/) — 免费额度大，国内访问快
- [OpenAI](https://platform.openai.com/) — GPT-4o 等
- [Kimi (Moonshot)](https://platform.moonshot.cn/) — 长文本能力强
- 支持任何兼容 OpenAI API 格式的大模型

## 项目结构

```
zhihuishuzhongshu/
├── main.py                  # 入口文件
├── requirements.txt         # Python 依赖
├── README.md               # 本文件
├── setup_mac.command       # macOS 启动脚本
├── setup_windows.bat        # Windows 安装启动脚本
├── app/
│   ├── config.py           # 配置管理
│   ├── database.py         # 数据库操作
│   ├── main_window.py      # 主窗口
│   └── widgets/            # 各功能面板
│       ├── chat_panel.py          # 会话面板
│       ├── knowledge_panel.py     # 知识库面板
│       ├── analysis_panel.py      # 分析记录面板
│       ├── model_config_panel.py  # 大模型配置面板
│       ├── logs_panel.py          # 运行日志面板
│       ├── skill_panel.py         # 技能管理面板
│       └── recycle_panel.py       # 回收站面板
└── core/
    ├── ai_service.py       # AI 服务（API 调用）
    ├── tools.py            # 工具函数（图表、报告、PPT）
    ├── file_processor.py   # 文件解析
    └── skill_manager.py    # 技能管理
```

## 技术栈

- **界面**: PyQt6
- **数据库**: SQLAlchemy + SQLite
- **AI**: 直接调用大模型 API（urllib，零外部依赖）
- **图表**: matplotlib
- **文档**: PyMuPDF / python-docx / openpyxl / python-pptx
- **打包**: PyInstaller

## 注意事项

- 所有数据存储在本地 `data/` 目录，不会上传云端
- 大模型的 API 密钥保存在本地数据库，请妥善保管
- 首次启动会自动创建 `data/` 目录和数据库
- Windows 打包后生成的 `.exe` 约 200MB，杀毒软件可能误报，添加信任即可
- 如需完全卸载，删除应用文件加和 `~/.zhihuishuniu/` 目录（Mac）或 `%USERPROFILE%\.zhihuishuniu\`（Windows）

## 协议

MIT License
