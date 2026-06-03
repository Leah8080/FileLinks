import re
import os
from pathlib import Path

# Color constants
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
CYAN = "\033[36m"
RED = "\033[31m"
RESET = "\033[0m"
BOLD = "\033[1m"

def get_site_url(project_path: Path) -> str:
    cname_path = project_path / "CNAME"
    url = ""
    
    if cname_path.exists():
        url = cname_path.read_text(encoding="utf-8").strip()
    
    if not url:
        print(f"\n{YELLOW}ℹ 未在 {project_path} 中找到 CNAME 文件或内容为空。{RESET}")
        # Support domain + optional path (e.g., sound.jp/app)
        site_regex = re.compile(
            r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}(?:/[a-zA-Z0-9._~:/?#\[\]@!$&\'()*+,;=%-]*)?$'
        )
        
        while True:
            print(f"{BOLD}{CYAN}▶ 请输入网站 URL{RESET} (例如 https://www.test.org): ", end="")
            site_input = input().strip()
            
            if not site_input:
                print(f"{RED}✘ URL 不能为空，请重新输入。{RESET}")
                continue
            
            # Strip protocol if present to validate the structure
            site_path = re.sub(r'^https?://', '', site_input)
            # Remove trailing slash for normalization if user entered one
            site_path = site_path.rstrip('/')
            
            if site_regex.match(site_path):
                url = f"https://{site_path}"
                break
            else:
                print(f"{RED}✘ 请输入有效的 URL 格式。{RESET}")
        
        # Save to CNAME
        cname_path.write_text(url, encoding="utf-8")
        print(f"{GREEN}✔ 已创建 CNAME 文件: {cname_path}{RESET}\n")

    # Normalize URL
    normalized_url = url
    if not normalized_url.startswith(("http://", "https://")):
        normalized_url = "https://" + normalized_url
    
    if not normalized_url.endswith("/"):
        normalized_url += "/"
        
    return normalized_url
