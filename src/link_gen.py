import os
from pathlib import Path
from typing import List, Dict
from src.filter import is_ignored
from src.config_loader import load_config

def get_file_icon(file_path: Path, icons_config: dict) -> str:
    ext = file_path.suffix.lower()
    icon = icons_config.get(ext)
    if not icon:
        icon = icons_config.get("default", "")
    return icon

def generate_links_grouped(project_path: Path, base_url: str, spec, icons_config: dict) -> Dict[str, List[dict]]:
    # { "Root Files": [{"name": "index.html", "url": "...", "icon": "🌐"}], ... }
    grouped = {"Root Files": []}
    
    for root, dirs, files in os.walk(project_path):
        rel_root = Path(root).relative_to(project_path)
        
        # Filter directories in place
        dirs[:] = [d for d in dirs if not is_ignored(Path(root) / d, project_path, spec)]
        
        # Sort files
        files.sort()
        
        for f in files:
            full_file_path = Path(root) / f
            if is_ignored(full_file_path, project_path, spec):
                continue
            
            rel_file = full_file_path.relative_to(project_path)
            url = base_url + str(rel_file).replace("\\", "/")
            
            # Get icon
            icon = get_file_icon(full_file_path, icons_config)
            
            item = {
                "name": f,
                "url": url,
                "icon": icon
            }
            
            if rel_root == Path("."):
                grouped["Root Files"].append(item)
            else:
                dir_key = str(rel_root).replace("\\", "/")
                if dir_key not in grouped:
                    grouped[dir_key] = []
                grouped[dir_key].append(item)
                
    return grouped

def write_link_md(project_path: Path, base_url: str, spec):
    config = load_config()
    icons_config = config.get("icons", {})
    project_icon = config.get("project_icon", "🚀")
    link_icon = config.get("link_icon", "🔗")
    folder_icon = config.get("folder_icon", "📁")
    
    grouped = generate_links_grouped(project_path, base_url, spec, icons_config)
    
    project_name = project_path.name
    
    lines = []
    lines.append(f"# {project_icon} {project_name}")
    lines.append("")
    lines.append(f"> {link_icon} {base_url}")
    lines.append("")
    
    # Helper to append group
    def append_group(group_name: str, items: List[dict]):
        if not items:
            return
        
        display_name = group_name
        if folder_icon:
            display_name = f"{folder_icon} {group_name}"
            
        lines.append(f"## {display_name}")
        lines.append("")
        for item in items:
            icon_str = f"{item['icon']} " if item['icon'] else ""
            lines.append(f"- {icon_str}{item['name']}")
            lines.append("")
            lines.append("  ```text")
            lines.append(f"  {item['url']}")
            lines.append("  ```")
            lines.append("")

    # 1. Root Files
    append_group("Root Files", grouped["Root Files"])
            
    # 2. Other directories
    sorted_dirs = sorted([k for k in grouped.keys() if k != "Root Files"])
    for d in sorted_dirs:
        append_group(d, grouped[d])
            
    link_md_path = project_path / "link.md"
    link_md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"已生成: {link_md_path}")
