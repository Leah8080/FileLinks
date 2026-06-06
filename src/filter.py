import os
from pathlib import Path
import pathspec
from src.config_loader import load_config
from src.ui import print_success

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
        
        if not target_file.exists():
            print_success(f"已创建忽略配置文件: {target_file.name}")
        print_success(f"已自动更新 {target_file.name}，增加了: {', '.join(missing_files)}")

def get_ignore_spec(project_path: Path):
    # 在获取 spec 前先确保物理文件已更新
    ensure_essential_ignores(project_path)
    
    config = load_config()
    ignore_config = config.get("ignore", [".gitignore", ".surgeignore"])
    
    all_patterns = []
    
    # 收集配置中的所有忽略模式
    for pattern in ignore_config:
        all_patterns.append(pattern)
        potential_file = project_path / pattern
        if potential_file.is_file():
            all_patterns.extend(potential_file.read_text(encoding="utf-8").splitlines())
    
    # 去重并去除空行
    all_patterns = list(set([p.strip() for p in all_patterns if p.strip()]))
    
    # 兜底确保这几个关键文件在内存 spec 中也存在
    for f in ["server.json", ".sync_state", ".sync_log", "link.md"]:
        if f not in all_patterns:
            all_patterns.append(f)

    spec = pathspec.PathSpec.from_lines('gitwildmatch', all_patterns)
    return spec

def is_ignored(path: Path, project_path: Path, spec: pathspec.PathSpec, is_dir: bool = False) -> bool:
    try:
        relative_path = path.relative_to(project_path)
        path_str = str(relative_path)
        if is_dir and not path_str.endswith("/"):
            path_str += "/"
        return spec.match_file(path_str)
    except ValueError:
        return False
