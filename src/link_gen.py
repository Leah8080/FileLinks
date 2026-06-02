import os
from pathlib import Path
from typing import List, Dict
from src.filter import is_ignored

def generate_links_grouped(project_path: Path, base_url: str, spec) -> Dict[str, List[str]]:
    # { "Root Files": [url1, url2], "dir1": [url3, url4] }
    grouped = {"Root Files": []}
    
    # Pre-calculate project name
    project_name = project_path.name
    
    for root, dirs, files in os.walk(project_path):
        rel_root = Path(root).relative_to(project_path)
        
        # Filter directories in place
        dirs[:] = [d for d in dirs if not is_ignored(Path(root) / d, project_path, spec)]
        
        # Sort files to ensure deterministic order
        files.sort()
        
        for f in files:
            file_path = Path(root) / f
            if is_ignored(file_path, project_path, spec):
                continue
            
            rel_file = file_path.relative_to(project_path)
            url = base_url + str(rel_file).replace("\\", "/")
            
            if rel_root == Path("."):
                grouped["Root Files"].append(url)
            else:
                # Use relative root string as key
                dir_key = str(rel_root).replace("\\", "/")
                if dir_key not in grouped:
                    grouped[dir_key] = []
                grouped[dir_key].append(url)
                
    return grouped

def write_link_md(project_path: Path, base_url: str, spec):
    grouped = generate_links_grouped(project_path, base_url, spec)
    project_name = project_path.name
    
    lines = []
    lines.append(f"# {project_name}")
    lines.append("")
    lines.append(f"> {base_url}")
    lines.append("")
    
    # 1. Root Files
    if grouped["Root Files"]:
        lines.append("## Root Files")
        lines.append("")
        for url in grouped["Root Files"]:
            lines.append("```text")
            lines.append(url)
            lines.append("```")
            lines.append("")
            
    # 2. Other directories
    sorted_dirs = sorted([k for k in grouped.keys() if k != "Root Files"])
    for d in sorted_dirs:
        lines.append(f"## {d}")
        lines.append("")
        for url in grouped[d]:
            lines.append("```text")
            lines.append(url)
            lines.append("```")
            lines.append("")
            
    link_md_path = project_path / "link.md"
    link_md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"已生成: {link_md_path}")
