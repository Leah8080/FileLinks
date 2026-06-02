import os
import sys
from pathlib import Path

# Add src to path if needed, but since we are running from root, 
# and src is a package (if we add __init__.py), it should work.
# Actually, I'll just use absolute imports if I treat src as a package.

from src.site_info import get_site_url
from src.filter import get_ignore_spec
from src.link_gen import generate_links, write_link_md

def main():
    try:
        path_input = input("Please enter the website project path: ").strip()
        if not path_input:
            print("Path cannot be empty.")
            return
        
        project_path = Path(path_input).resolve()
        if not project_path.exists() or not project_path.is_dir():
            print(f"Error: {project_path} is not a valid directory.")
            return

        print(f"Processing project at: {project_path}")
        
        # 1. Get/Normalize Site URL
        base_url = get_site_url(project_path)
        print(f"Website URL: {base_url}")
        
        # 2. Get Ignore Spec and ensure link.md is ignored
        spec = get_ignore_spec(project_path)
        
        # 3. Generate links
        links = generate_links(project_path, base_url, spec)
        
        # 4. Write link.md
        write_link_md(project_path, links)
        
        print("Success!")

    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
