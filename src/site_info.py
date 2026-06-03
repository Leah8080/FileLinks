import re
import os
from pathlib import Path
from src.ui import print_success, print_info, print_error, ask_input

def get_site_url(project_path: Path) -> str:
    cname_path = project_path / "CNAME"
    url = ""
    
    if cname_path.exists():
        url = cname_path.read_text(encoding="utf-8").strip()
    
    if not url:
        print_error(f"在 {project_path} 中未找到 CNAME 文件或内容为空。")
        # Support domain + optional path (e.g., sound.jp/app)
        site_regex = re.compile(
            r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}(?:/[a-zA-Z0-9._~:/?#\[\]@!$&\'()*+,;=%-]*)?$'
        )
        
        while True:
            site_input = ask_input("请输入网站 URL (例如 https://www.test.org): ")
            
            if not site_input:
                print_error("URL 不能为空，请重新输入。")
                continue
            
            # Strip protocol if present to validate the structure
            site_path = re.sub(r'^https?://', '', site_input)
            # Remove trailing slash for normalization if user entered one
            site_path = site_path.rstrip('/')
            
            if site_regex.match(site_path):
                url = f"https://{site_path}"
                break
            else:
                print_error("请输入有效的 URL 格式。")
        
        # Save to CNAME
        cname_path.write_text(url, encoding="utf-8")
        print_success(f"已创建 CNAME 文件: {cname_path}")

    # Normalize URL
    normalized_url = url
    if not normalized_url.startswith(("http://", "https://")):
        normalized_url = "https://" + normalized_url
    
    if not normalized_url.endswith("/"):
        normalized_url += "/"
        
    return normalized_url
