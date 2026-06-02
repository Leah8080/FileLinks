import os
from pathlib import Path
from typing import List, Set
from src.filter import is_ignored

def generate_links(project_path: Path, base_url: str, spec) -> List[str]:
    links = []
    
    # Add the base root itself
    links.append(base_url)
    
    # We want to sort: Root files, then other directories and their contents
    root_files = []
    other_items = []
    
    for root, dirs, files in os.walk(project_path):
        rel_root = Path(root).relative_to(project_path)
        
        # Filter directories in place to skip ignored ones
        dirs[:] = [d for d in dirs if not is_ignored(Path(root) / d, project_path, spec)]
        
        for d in dirs:
            dir_path = Path(root) / d
            rel_dir = dir_path.relative_to(project_path)
            url = base_url + str(rel_dir).replace("\\", "/") + "/"
            other_items.append(url)
            
        for f in files:
            file_path = Path(root) / f
            if is_ignored(file_path, project_path, spec):
                continue
            
            rel_file = file_path.relative_to(project_path)
            url = base_url + str(rel_file).replace("\\", "/")
            
            if rel_root == Path("."):
                root_files.append(url)
            else:
                other_items.append(url)
                
    # Sort root files and other items alphabetically
    root_files.sort()
    other_items.sort()
    
    return [base_url] + root_files + other_items

def write_link_md(project_path: Path, links: List[str]):
    content = "```text\n"
    # Remove duplicates and keep order (though our walk shouldn't have duplicates)
    seen = set()
    unique_links = []
    for l in links:
        if l not in seen:
            unique_links.append(l)
            seen.add(l)
            
    content += "\n".join(unique_links)
    content += "\n```"
    
    link_md_path = project_path / "link.md"
    link_md_path.write_text(content, encoding="utf-8")
    print(f"Generated {link_md_path}")
