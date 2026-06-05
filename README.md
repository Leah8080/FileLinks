# FileLinks - 网站文件同步管理与链接地图生成工具

`FileLinks` 是一个基于 Python 的自动化工具，旨在为静态个人网站提供高效的本地与远程管理方案。它不仅能生成结构化的链接地图 (`link.md`)，还支持高效的 FTP/SFTP 同步与项目历史管理。

## 🌟 核心特性

- **🚀 远程同步**：支持 FTP 和 SFTP 协议，具备智能增量同步功能（基于文件大小与 MD5 校验），支持双向同步（上传/下载）。
- **🔗 智能链接生成**：自动扫描项目文件，根据 `CNAME` 生成结构化的 Markdown 链接地图。支持**按目录分组展示**，并可为不同后缀的文件自动匹配图标。
- **📜 历史记录管理**：自动保存最近处理的项目路径，支持通过序号快速切换，告别重复输入。
- **🎨 交互式 UI**：基于 `Rich` 库打造的高颜值终端界面，提供清晰的进度条、状态面板和操作菜单。
- **🔍 智能过滤**：深度集成 `pathspec`，支持读取 `.gitignore` 等忽略规则，确保无关文件不被同步或索引。

## 📂 项目结构

```text
.
├── main.py              # 程序入口（交互式菜单）
├── config.json          # 全局配置文件（项目/目录图标、后缀图标、忽略规则等）
├── pyproject.toml       # 项目依赖管理 (uv)
├── history.json         # [自动生成] 项目历史记录
├── src/                 # 源代码目录
│   ├── history_manager.py # 历史记录管理
│   ├── sync.py          # FTP/SFTP 同步引擎
│   ├── ui.py            # Rich 终端界面封装
│   ├── config_loader.py # 配置加载
│   ├── filter.py        # 忽略规则过滤
│   ├── link_gen.py      # 链接地图生成
│   └── site_info.py     # 站点 URL 处理
└── README.md            # 项目说明文档
```

## 🚀 快速开始

### 前提条件

确保已安装 [uv](https://github.com/astral-sh/uv)。

### 运行步骤

1. 克隆或下载本项目到本地。
2. 在项目根目录下运行：

   ```bash
   uv run main.py
   ```

3. **初次使用**：输入您网站项目的绝对路径。
4. **后续使用**：直接输入历史记录中的序号即可快速进入项目。

## ⚙️ 配置说明

### 全局配置 (`config.json`)

您可以自定义链接地图的外观和过滤行为：

```json
{
  "ignore": [".gitignore", ".surgeignore"],
  "project_icon": "🚀",  // 项目标题图标
  "link_icon": "🔗",     // 网站链接图标
  "folder_icon": "📁",   // 目录分组图标
  "icons": {
    "default": "📄",
    ".html": "🌐",
    ...
  }
}
```

### 远程同步配置 (`server.json`)

若需使用同步功能，请在您的**网站项目根目录**（而非本工具目录）创建 `server.json`：

**SFTP 示例：**
```json
{
  "sftp": {
    "host": "your.server.com",
    "port": 22,
    "user": "username",
    "password": "password",
    "remote_path": "/www/html"
  }
}
```

**FTP 示例：**
```json
{
  "ftp": {
    "host": "ftp.your.server.com",
    "port": 21,
    "user": "username",
    "password": "password",
    "remote_path": "/public_html"
  }
}
```

## 🛠️ 常见问题

- **同步时如何忽略特定文件？**
  工具会自动读取项目下的 `.gitignore` 或 `.surgeignore`。您也可以在 `config.json` 的 `ignore_files` 中添加其他忽略规则文件。

---
*Created by Gemini CLI*

