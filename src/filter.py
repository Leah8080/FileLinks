import os
from pathlib import Path
import pathspec

def get_ignore_spec(project_path: Path):
    ignore_files = [".gitignore", ".surgeignore"]
    ignore_content = []
    found_file = None
    
    for filename in ignore_files:
        p = project_path / filename
        if p.exists():
            content = p.read_text(encoding="utf-8")
            ignore_content.append(content)
            found_file = p
            break
    
    # Ensure link.md is ignored
    is_link_md_ignored = False
    for content in ignore_content:
        lines = [line.strip() for line in content.splitlines()]
        if "link.md" in lines:
            is_link_md_ignored = True
            break
            
    if not is_link_md_ignored:
        if found_file:
            current_content = found_file.read_text(encoding="utf-8")
            if not current_content.endswith("\n") and current_content:
                with open(found_file, "a", encoding="utf-8") as f:
                    f.write("\n")
            with open(found_file, "a", encoding="utf-8") as f:
                f.write("link.md\n")
            print(f"已将 link.md 添加到 {found_file.name}")
        else:
            # Create .gitignore if none exists
            gitignore_path = project_path / ".gitignore"
            gitignore_path.write_text("link.md\n", encoding="utf-8")
            found_file = gitignore_path
            print(f"已创建 .gitignore 并添加 link.md")
        
        # Re-read if it was updated
        ignore_content = [found_file.read_text(encoding="utf-8")]

    # Combine all lines and handle patterns
    all_patterns = []
    for content in ignore_content:
        all_patterns.extend(content.splitlines())
    
    # Always ignore .git
    all_patterns.append(".git/")
    
    spec = pathspec.PathSpec.from_lines('gitwildmatch', all_patterns)
    return spec

def is_ignored(path: Path, project_path: Path, spec: pathspec.PathSpec) -> bool:
    try:
        relative_path = path.relative_to(project_path)
        # pathspec expects strings
        return spec.match_file(str(relative_path))
    except ValueError:
        return False
