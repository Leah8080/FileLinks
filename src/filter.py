import os
from pathlib import Path
import pathspec
from src.config_loader import load_config
from src.ui import print_success

def get_ignore_spec(project_path: Path):
    config = load_config()
    ignore_config = config.get("ignore", [])
    
    all_patterns = []
    ignore_source_files = []
    
    # 1. 收集配置中的模式，并识别哪些是需要读取内容的源文件
    for pattern in ignore_config:
        all_patterns.append(pattern)
        # 如果模式对应一个现有的文件，我们将其视为忽略规则的来源
        potential_file = project_path / pattern
        if potential_file.is_file():
            ignore_source_files.append(potential_file)
    
    # 2. 读取这些源文件的内容并加入模式列表
    ignore_file_contents = []
    for f in ignore_source_files:
        content = f.read_text(encoding="utf-8")
        ignore_file_contents.append(content)
        all_patterns.extend(content.splitlines())
    
    # 3. 确保 link.md 被追加到忽略列表中
    is_link_md_ignored = False
    # 检查配置和已读文件中是否有 link.md
    if "link.md" in ignore_config:
        is_link_md_ignored = True
    else:
        for content in ignore_file_contents:
            if "link.md" in [line.strip() for line in content.splitlines()]:
                is_link_md_ignored = True
                break
            
    if not is_link_md_ignored:
        # 优先追加到第一个找到的忽略源文件，否则创建 .gitignore
        target_file = ignore_source_files[0] if ignore_source_files else (project_path / ".gitignore")
        
        if target_file.exists():
            current_content = target_file.read_text(encoding="utf-8")
            suffix = "" if (not current_content or current_content.endswith("\n")) else "\n"
            with open(target_file, "a", encoding="utf-8") as f:
                f.write(f"{suffix}link.md\n")
            print_success(f"已将 link.md 添加到 {target_file.name}")
        else:
            target_file.write_text("link.md\n", encoding="utf-8")
            all_patterns.append(target_file.name) # 确保新创建的忽略文件也被忽略
            print_success(f"已创建 {target_file.name} 并添加 link.md")
        
        all_patterns.append("link.md")

    # 4. 确保 server.json 被忽略 (包含敏感信息)
    if "server.json" not in all_patterns:
        all_patterns.append("server.json")

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
