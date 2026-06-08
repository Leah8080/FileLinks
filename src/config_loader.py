import json
from pathlib import Path
from src.ui import print_warning, print_error, print_info

# 定义默认配置，确保程序在配置缺失时仍能运行
DEFAULT_CONFIG = {
    "max_history": 10,
    "max_workers": 3,
    "preview_port": 8000,
    "remote_scan_on_state_mismatch": True,
    "ignore": [
        ".gitignore",
        ".surgeignore"
    ],
    "project_icon": "🚀",
    "link_icon": "🔗",
    "folder_icon": "📁",
    "icons": {
        ".html": "🌐",
        ".js": "📜",
        ".css": "🎨",
        ".txt": "📄",
        ".md": "📝",
        "default": "📄"
    }
}

def validate_config(config: dict) -> dict:
    """
    验证配置文件的完整性，并补充缺失的字段
    """
    validated = DEFAULT_CONFIG.copy()
    
    if not isinstance(config, dict):
        print_warning("配置文件格式不正确，将使用默认配置。")
        return validated

    # 验证并更新顶层字段
    for key in ["project_icon", "link_icon", "folder_icon"]:
        if key in config and isinstance(config[key], str):
            validated[key] = config[key]

    for key in ["max_history", "max_workers", "preview_port"]:
        if key in config and isinstance(config[key], int):
            validated[key] = config[key]

    for key in ["remote_scan_on_state_mismatch"]:
        if key in config and isinstance(config[key], bool):
            validated[key] = config[key]
            
    # 验证并合并 ignore 列表
    if "ignore" in config:
        if isinstance(config["ignore"], list):
            # 确保列表项都是字符串
            valid_patterns = [p for p in config["ignore"] if isinstance(p, str)]
            validated["ignore"] = valid_patterns
        else:
            print_warning(f"'ignore' 字段应为列表，当前类型为 {type(config['ignore']).__name__}。")

    # 验证并合并 icons 字典
    if "icons" in config:
        if isinstance(config["icons"], dict):
            # 补充默认图标
            validated["icons"].update({k: v for k, v in config["icons"].items() if isinstance(v, str)})
        else:
            print_warning(f"'icons' 字段应为对象，当前类型为 {type(config['icons']).__name__}。")
            
    return validated

def load_config() -> dict:
    """
    加载并验证配置文件
    """
    config_path = Path("config.json")
    config_data = {}
    
    if config_path.exists():
        try:
            content = config_path.read_text(encoding="utf-8")
            if content.strip():
                config_data = json.loads(content)
        except json.JSONDecodeError as e:
            # 仅在文件格式真的错误时保留警告，并增加停顿以便用户看清
            print_error(f"config.json 格式错误 (行 {e.lineno}, 列 {e.colno}): {e.msg}")
            from src.ui import ask_input
            ask_input("程序将尝试使用默认配置继续运行，按回车键确认...")
        except Exception:
            pass
    
    return validate_config(config_data)
