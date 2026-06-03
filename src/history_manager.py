import json
from pathlib import Path
from datetime import datetime

HISTORY_FILE = Path("history.json")
MAX_HISTORY = 10

def load_history():
    """加载历史记录"""
    if not HISTORY_FILE.exists():
        return []
    try:
        content = HISTORY_FILE.read_text(encoding="utf-8")
        if not content.strip():
            return []
        history = json.loads(content)
        if isinstance(history, list):
            return history
    except Exception:
        pass
    return []

def save_history(project_path: str):
    """保存项目路径到历史记录"""
    history = load_history()
    project_path = str(Path(project_path).resolve())
    
    # 移除已存在的相同路径
    history = [item for item in history if item['path'] != project_path]
    
    # 添加新记录到最前面
    new_entry = {
        "path": project_path,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    history.insert(0, new_entry)
    
    # 限制数量
    history = history[:MAX_HISTORY]
    
    try:
        HISTORY_FILE.write_text(json.dumps(history, indent=4, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"保存历史记录失败: {e}")

def clear_history():
    """清空历史记录"""
    if HISTORY_FILE.exists():
        HISTORY_FILE.unlink()
