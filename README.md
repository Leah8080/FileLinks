# FileLinks - 个人网站链接地图生成工具

`FileLinks` 是一个基于 Python 的自动化工具，专门用于为静态个人网站生成结构化的链接地图 (`link.md`)。

## 🌟 核心特性

- **智能 CNAME 处理**：自动读取 `CNAME` 文件，若缺失则引导用户输入并自动创建，支持 URL 自动规范化。
- **高级过滤逻辑**：支持从 `config.json` 指定忽略文件（如 `.gitignore`, `.surgeignore`），并能读取这些文件的内容作为过滤规则。

## 📂 项目结构

```text
.
├── main.py              # 程序入口脚本
├── config.json          # 核心配置文件（图标、忽略规则等）
├── pyproject.toml       # 项目依赖管理 (uv)
├── src/                 # 源代码目录
│   ├── __init__.py
│   ├── config_loader.py # 配置加载模块
│   ├── filter.py        # 忽略规则与过滤逻辑
│   ├── link_gen.py      # Markdown 文档生成引擎
│   └── site_info.py     # CNAME 与 URL 处理模块
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

3. 根据提示输入您的个人网站项目所在的绝对或相对路径。

## 🛠️ 常见问题

- **如何添加新的图标？**
  在 `config.json` 的 `icons` 字典中添加 `"后缀名": "图标"` 即可。
- **脚本会修改我的项目吗？**
  脚本仅会在您的项目根目录创建或更新 `CNAME` 和 `link.md`，并可能在您的 `.gitignore` 中追加一行 `link.md`。

---
*Created by Gemini CLI*
