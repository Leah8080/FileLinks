import os
import sys
from pathlib import Path

# Add src to path if needed, but since we are running from root, 
# and src is a package (if we add __init__.py), it should work.
# Actually, I'll just use absolute imports if I treat src as a package.

from src.site_info import get_site_url
from src.filter import get_ignore_spec
from src.link_gen import write_link_md

def main():
    try:
        path_input = input("请输入个人网站项目路径: ").strip()
        if not path_input:
            print("路径不能为空。")
            return
        
        project_path = Path(path_input).resolve()
        if not project_path.exists() or not project_path.is_dir():
            print(f"错误: {project_path} 不是有效的目录。")
            return

        print(f"正在处理项目: {project_path}")
        
        # 1. 获取并规范化网站 URL
        base_url = get_site_url(project_path)
        print(f"网站链接: {base_url}")
        
        # 2. 获取忽略配置并确保 link.md 被忽略
        spec = get_ignore_spec(project_path)
        
        # 3. 生成并写入 link.md
        write_link_md(project_path, base_url, spec)
        
        print("成功！")

    except Exception as e:
        print(f"发生意外错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
