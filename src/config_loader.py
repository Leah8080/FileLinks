import json
from pathlib import Path

def load_config() -> dict:
    config_path = Path("config.json")
    if config_path.exists():
        try:
            return json.loads(config_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"警告: 读取 config.json 失败: {e}")
    return {"ignore": [], "icons": {}}
