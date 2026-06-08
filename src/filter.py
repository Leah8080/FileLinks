import os
from pathlib import Path
import pathspec
from src.config_loader import load_config

def ensure_essential_ignores(project_path: Path):
    """
    确保必要的工具文件（如 server.json, .sync_state 等）被物理添加到忽略配置文件中。
    """
    config = load_config()
    ignore_config = config.get("ignore", [".gitignore", ".surgeignore"])
    
    # 确定要写入的目标文件（优先使用第一个存在的，否则创建 .gitignore）
    target_file = project_path / ".gitignore"
    for pattern in ignore_config:
        potential = project_path / pattern
        if potential.is_file():
            target_file = potential
            break

    # 定义必须忽略的文件
    essential_files = ["link.md", "server.json", ".sync_state", ".sync_log"]
    
    # 读取当前内容
    current_lines = []
    if target_file.exists():
        current_lines = [line.strip() for line in target_file.read_text(encoding="utf-8").splitlines()]
    
    # 找出缺失的项
    missing_files = [f for f in essential_files if f not in current_lines]
    
    if missing_files:
        content_to_append = ""
        if target_file.exists() and current_lines and not target_file.read_text(encoding="utf-8").endswith("\n"):
            content_to_append += "\n"
        
        for f in missing_files:
            content_to_append += f"{f}\n"
            
        with open(target_file, "a", encoding="utf-8") as f:
            f.write(content_to_append)
        
        # 已移除 print_success 提示，实现静默更新

def get_ignore_spec(project_path: Path):
    # 在获取 spec 前先确保物理文件已更新
    ensure_essential_ignores(project_path)
    
    config = load_config()
    ignore_config = config.get("ignore", [".gitignore", ".surgeignore"])
    
    all_patterns = []
    pattern_sources = []
    seen_patterns = set()

    def add_pattern(pattern: str, source: str):
        pattern = pattern.strip()
        if not pattern or pattern.startswith("#") or pattern in seen_patterns:
            return
        seen_patterns.add(pattern)
        all_patterns.append(pattern)
        pattern_sources.append((pattern, source))
    
    # 收集配置中的所有忽略模式
    for pattern in ignore_config:
        add_pattern(pattern, "config.json:ignore")
        potential_file = project_path / pattern
        if potential_file.is_file():
            for line_no, line in enumerate(potential_file.read_text(encoding="utf-8").splitlines(), start=1):
                add_pattern(line, f"{potential_file.name}:{line_no}")
    
    # 兜底确保这几个关键文件在内存 spec 中也存在
    for f in ["server.json", ".sync_state", ".sync_log", "link.md"]:
        add_pattern(f, "内置安全规则")

    spec = pathspec.PathSpec.from_lines('gitwildmatch', all_patterns)
    spec._filelinks_rule_sources = pattern_sources
    return spec

def is_ignored(path: Path, project_path: Path, spec: pathspec.PathSpec, is_dir: bool = False) -> bool:
    try:
        relative_path = path.relative_to(project_path)
        return is_ignored_path(relative_path.as_posix(), spec, is_dir)
    except ValueError:
        return False

def is_ignored_path(path_str: str, spec: pathspec.PathSpec, is_dir: bool = False) -> bool:
    return spec.match_file(_normalize_match_path(path_str, is_dir))

def get_ignore_match_source(path_str: str, spec: pathspec.PathSpec, is_dir: bool = False) -> str:
    match_path = _normalize_match_path(path_str, is_dir)
    for pattern, source in getattr(spec, "_filelinks_rule_sources", []):
        if pathspec.PathSpec.from_lines("gitwildmatch", [pattern]).match_file(match_path):
            return source
    return "忽略配置"

def _normalize_match_path(path_str: str, is_dir: bool = False) -> str:
    path_str = path_str.replace("\\", "/").strip("/")
    if is_dir and not path_str.endswith("/"):
        path_str += "/"
    return path_str
