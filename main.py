import os
import sys
from pathlib import Path

# Add src to path if needed
from src.site_info import get_site_url
from src.filter import get_ignore_spec
from src.link_gen import write_link_md
from src.ui import print_success, print_info, print_error, print_step, ask_input, print_menu, print_header, print_history_table
from src.sync import sync_files
from src.history_manager import load_history, save_history

def clear_screen():
    """清屏函数，兼容Windows和Linux/Mac"""
    os.system('cls' if os.name == 'nt' else 'clear')

def select_project_workflow(header_title):
    """选择项目路径工作流"""
    while True:
        clear_screen()
        print_header(header_title)
        
        history = load_history()
        if history:
            print_history_table(history)
            prompt_msg = "请输入序号选择历史项目，或输入新的项目路径"
        else:
            prompt_msg = "请输入网站项目路径"
            
        path_input = ask_input(prompt_msg)
        
        if not path_input:
            print_error("输入不能为空，请重新输入...")
            input("\n按回车键继续...")
            continue
        
        # 尝试作为序号解析
        if path_input.isdigit():
            idx = int(path_input) - 1
            if 0 <= idx < len(history):
                project_path = Path(history[idx]['path'])
            else:
                print_error("无效的序号，请重新输入...")
                input("\n按回车键继续...")
                continue
        else:
            project_path = Path(path_input).resolve()
            
        if not project_path.exists() or not project_path.is_dir():
            print_error(f"不是有效的目录: {project_path}")
            input("\n按回车键继续...")
            continue
        
        # 保存到历史记录
        save_history(str(project_path))
        return project_path

def generate_links_workflow(project_path):
    # 生成链接逻辑封装
    print_step(f"处理项目: {project_path}")
    
    # 1. 获取并规范化网站 URL
    print_step("提取项目网站链接...")
    base_url = get_site_url(project_path)
    print_info(f"网站链接: {base_url}")
    
    # 2. 获取忽略配置并确保 link.md 被忽略
    spec = get_ignore_spec(project_path)
    
    # 3. 生成并写入 link.md
    print_step("生成网站文件访问链接...")
    write_link_md(project_path, base_url, spec)
    
    print_success("链接生成完成！")

def main():
    header_title = "🌐 网站文件管理工具"
    try:
        project_path = select_project_workflow(header_title)

        while True:
            clear_screen()
            print_header(header_title)
            print_info(f"当前项目: {project_path}")
            
            options = ["同步文件", "生成链接", "切换项目", "退出脚本"]
            print_menu("文件管理菜单", options)
            
            choice = ask_input("请选择操作 (0-3): ")
            
            if choice == "1":
                # 同步文件
                print_step("准备同步文件...")
                try:
                    spec = get_ignore_spec(project_path)
                    if sync_files(project_path, spec):
                        # 同步成功后询问是否生成链接
                        from src.ui import ask_confirm
                        if ask_confirm("同步完成，是否立即生成文件链接?"):
                            generate_links_workflow(project_path)
                except Exception as e:
                    print_error(f"同步失败: {e}")
                input("\n按回车键继续...")
                
            elif choice == "2":
                # 生成链接
                try:
                    generate_links_workflow(project_path)
                except Exception as e:
                    print_error(f"生成链接失败: {e}")
                input("\n按回车键继续...")
            
            elif choice == "3":
                # 切换项目
                project_path = select_project_workflow(header_title)
                
            elif choice == "0":
                print_info("退出脚本，再见！")
                break
            else:
                print_error("无效的选择，请重新输入。")
                input("\n按回车键继续...")

    except Exception as e:
        print_error(f"发生意外错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
