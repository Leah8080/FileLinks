import hashlib
import json
from pathlib import Path
from src.ui import print_warning
from src.filter import is_ignored

SYNC_STATE_FILENAME = ".sync_state"
SYNC_LOG_FILENAME = ".sync_log"

def calculate_md5(file_path: Path) -> str:
    """计算本地文件的 MD5 校验和"""
    hash_md5 = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except Exception:
        return ""

def load_sync_state(project_path: Path) -> dict:
    """加载本地同步状态缓存"""
    state_file = project_path / SYNC_STATE_FILENAME
    if state_file.exists():
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_sync_state(project_path: Path, state: dict):
    """保存当前同步状态到本地"""
    state_file = project_path / SYNC_STATE_FILENAME
    try:
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print_warning(f"无法保存同步状态缓存: {e}")

def get_local_structure(path: Path, project_root: Path, spec):
    """递归获取本地文件结构"""
    structure = {}
    for item in path.iterdir():
        if is_ignored(item, project_root, spec, item.is_dir()):
            continue
        
        rel_path = item.relative_to(project_root).as_posix().strip("/")
        if item.is_dir():
            structure[rel_path] = {"type": "dir", "size": 0}
            structure.update(get_local_structure(item, project_root, spec))
        else:
            structure[rel_path] = {
                "type": "file",
                "size": item.stat().st_size,
                "md5": calculate_md5(item)
            }
    return structure

def normalize_path(path_str):
    """确保路径使用正斜杠，且不带末尾斜杠。保留起始斜杠以维持绝对路径性质。"""
    if not path_str: return "/"
    p = path_str.replace("\\", "/").strip("/")
    return "/" + p if p else "/"
