import os
import sys
from pathlib import Path

# Add src to path if needed
from src.site_info import get_site_url
from src.filter import get_ignore_spec
from src.link_gen import write_link_md
from src.ui import print_success, print_info, print_error, print_step, ask_input, print_menu, print_header, print_history_table, console
from src.sync import sync_to_remote, sync_from_remote
from src.history_manager import load_history, save_history

header_title = " " * 25 +"🌐 网站文件管理" + " " * 25
sub_title = "v1.0.0 • Efficient Website Management"
menu_title = "我的项目"

def clear_screen():
    """清屏函数，兼容Windows和Linux/Mac"""
    os.system('cls' if os.name == 'nt' else 'clear')

def select_project_workflow():
    """选择项目路径工作流"""
    while True:
        clear_screen()
        print_header(header_title, sub_title)
        
        history = load_history()
        if history:
            print_history_table(history)
            prompt_msg = "可输入序号或新的项目路径 (输入0退出脚本)\n⏳ 请输入"
        else:
            prompt_msg = "输入网站项目路径 (输入0退出脚本)\n⏳ 请输入"
            
        path_input = ask_input(prompt_msg)
        
        if not path_input:
            print_error("输入不能为空，请重新输入...")
            input("\n按回车键继续...")
            continue
        
        if path_input == "0":
            print_info("退出脚本，再见！")
            sys.exit(0)
        
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
   
    try:
        project_path = select_project_workflow()

        while True:
            clear_screen()
            print_header(header_title, sub_title)
            
            # 构造合并后的面板内容
            menu_content = f"[bold cyan]📂 项目路径:\n[/bold cyan] [bold green]{project_path}[/bold green]\n"
            menu_content += "[dim]─[/dim]" * 60 + "\n"
            
            options = [
                "同步本地 [dim]上传本地文件到远程主机[/dim]", 
                "同步云端 [dim]从远程主机下载文件到本地[/dim]", 
                "生成链接 [dim]为项目文件生成访问链接[/dim]", 
                "切换项目 [dim]选择其他网站项目路径[/dim]", 
                "退出脚本"
            ]
            
            for i, option in enumerate(options):
                idx = i + 1 if "退出" not in option else 0
                menu_content += f"[bold blue]{idx}.[/bold blue] {option}\n"
            
            from rich.panel import Panel
            console.print(Panel(menu_content.strip(), title=f"[bold cyan]🚀 {menu_title}[/bold cyan]", border_style="cyan", expand=False))
            
            choice = ask_input("请选择操作 (0-4)")
            
            if choice == "1":
                # 同步本地
                print_step("准备同步到远程...")
                try:
                    spec = get_ignore_spec(project_path)
                    if sync_to_remote(project_path, spec):
                        # 同步成功后询问是否生成链接
                        from src.ui import ask_confirm
                        if ask_confirm("同步完成，是否立即生成文件链接?"):
                            generate_links_workflow(project_path)
                except Exception as e:
                    print_error(f"同步失败: {e}")
                input("\n按回车键继续...")
            
            elif choice == "2":
                # 同步云端
                print_step("准备从远程同步...")
                try:
                    spec = get_ignore_spec(project_path)
                    if sync_from_remote(project_path, spec):
                        # 同步成功后询问是否生成链接
                        from src.ui import ask_confirm
                        if ask_confirm("同步完成，是否立即生成文件链接?"):
                            generate_links_workflow(project_path)
                except Exception as e:
                    print_error(f"同步失败: {e}")
                input("\n按回车键继续...")
                
            elif choice == "3":
                # 生成链接
                try:
                    generate_links_workflow(project_path)
                except Exception as e:
                    print_error(f"生成链接失败: {e}")
                input("\n按回车键继续...")
            
            elif choice == "4":
                # 切换项目
                project_path = select_project_workflow()
                
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
