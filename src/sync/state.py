from src.filter import get_ignore_match_source, is_ignored_path
from src.sync.comm import push_remote_state
from src.sync.scanner import load_sync_state, save_sync_state
from src.ui import print_info


def filter_structure(struct, spec):
    """移除状态缓存中后来被忽略规则覆盖的路径，并返回被过滤项。"""
    if not struct:
        return struct, {}
    filtered_struct = {}
    ignored_paths = {}
    for path, info in struct.items():
        is_dir = info.get("type") == "dir"
        if is_ignored_path(path, spec, is_dir):
            ignored_info = dict(info)
            ignored_info["ignored_by"] = ignored_info.get("ignored_by") or get_ignore_match_source(path, spec, is_dir)
            ignored_info["origin"] = ignored_info.get("origin") or "state"
            ignored_paths[path] = ignored_info
        else:
            filtered_struct[path] = info
    return filtered_struct, ignored_paths


def count_files(struct):
    return sum(1 for info in struct.values() if info.get("type") == "file")


def load_filtered_local_state(project_path, spec):
    state = load_sync_state(project_path)
    clean_state, ignored = filter_structure(state, spec)
    if ignored:
        save_sync_state(project_path, clean_state)
        print_info(f"已清理本地同步状态中的 {len(ignored)} 个忽略项。")
    return clean_state, ignored


def save_clean_state(project_path, state, spec):
    clean_state, _ = filter_structure(state, spec)
    save_sync_state(project_path, clean_state)
    return clean_state


def push_clean_remote_state(protocol, cfg, state, spec):
    clean_state, _ = filter_structure(state, spec)
    push_remote_state(protocol, cfg, clean_state)
    return clean_state


def merge_ignored(*groups):
    merged = {}
    for group in groups:
        for path, info in group.items():
            existing = merged.get(path, {})
            origins = set(str(existing.get("origin", "")).split("+")) if existing.get("origin") else set()
            if info.get("origin"):
                origins.add(info["origin"])
            merged[path] = {**existing, **info}
            if origins:
                merged[path]["origin"] = "+".join(sorted(origins))
    return merged
