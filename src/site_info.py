import os
from pathlib import Path

def get_site_url(project_path: Path) -> str:
    cname_path = project_path / "CNAME"
    url = ""
    
    if cname_path.exists():
        url = cname_path.read_text(encoding="utf-8").strip()
    
    if not url:
        print(f"No CNAME file found or empty in {project_path}")
        url = input("Please enter the website URL (e.g., https://test.haha.org): ").strip()
        while not url:
            url = input("URL cannot be empty. Please enter the website URL: ").strip()
        
        # Save to CNAME
        cname_path.write_text(url, encoding="utf-8")
        print(f"CNAME file created at {cname_path}")

    # Normalize URL
    # Handle cases: test.haha.org, https://test.haha.org, https://test.haha.org/
    normalized_url = url
    if not normalized_url.startswith(("http://", "https://")):
        normalized_url = "https://" + normalized_url
    
    if not normalized_url.endswith("/"):
        normalized_url += "/"
        
    return normalized_url
