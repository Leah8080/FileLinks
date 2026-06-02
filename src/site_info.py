import os
from pathlib import Path

def get_site_url(project_path: Path) -> str:
    cname_path = project_path / "CNAME"
    url = ""
    
    if cname_path.exists():
        url = cname_path.read_text(encoding="utf-8").strip()
    
    if not url:
        print(f"在 {project_path} 中未找到 CNAME 文件或内容为空。")
        url = input("请输入网站 URL (例如 https://test.haha.org): ").strip()
        while not url:
            url = input("URL 不能为空，请重新输入: ").strip()
        
        # Save to CNAME
        cname_path.write_text(url, encoding="utf-8")
        print(f"已创建 CNAME 文件: {cname_path}")

    # Normalize URL
    # Handle cases: test.haha.org, https://test.haha.org, https://test.haha.org/
    normalized_url = url
    if not normalized_url.startswith(("http://", "https://")):
        normalized_url = "https://" + normalized_url
    
    if not normalized_url.endswith("/"):
        normalized_url += "/"
        
    return normalized_url
