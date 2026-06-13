import os
import sys
from pathlib import Path

# Add src to path if needed
from src.site_info import get_site_url
from src.filter import get_ignore_spec, ensure_essential_ignores
from src.link_gen import write_link_md
from src.ui import print_success, print_info, print_error, print_step, ask_input, print_menu, print_header, print_history_table, console
from src.sync import sync_to_remote, sync_from_remote
from src.history_manager import load_history, save_history
from src.preview_server import preview_manager
from src.config_loader import load_config

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
            if history and 0 <= idx < len(history):
                project_path = Path(history[idx]['path'])
            else:
                print_error("无效的序号，请重新输入...")
                input("\n按回车键继续...")
                continue
        else:
            # 清理路径字符串
            clean_path = path_input.strip('"').strip("'")
            project_path = Path(clean_path).resolve()
            
        if not project_path.exists() or not project_path.is_dir():
            print_error(f"不是有效的目录: {project_path}")
            input("\n按回车键继续...")
            continue
        
        # 自动处理忽略文件
        try:
            ensure_essential_ignores(project_path)
        except Exception as e:
            print_error(f"初始化忽略文件失败: {e}")

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
            
            # 读取主机配置信息
            from src.sync import get_server_config
            from src.site_info import get_cname_domain
            server_info = get_server_config(project_path)
            cname_domain = get_cname_domain(project_path)
            
            if server_info:
                proto, cfg = server_info
                # 脱敏显示密码
                mask_pass = "*" * len(cfg.get("password", "")) if cfg.get("password") else "[yellow]为配置[/]"
                remote_path_display = cfg.get('remote_path') if cfg.get('remote_path') else "[yellow]未配置[/]([dim]使用根路径[/][green]'/'[/])"
                host_display = f"[bold cyan]🖥️ 远程主机:[/bold cyan] {proto}://{cfg.get('user')}@{cfg.get('host')}:{cfg.get('port')}\n"
                host_display += f"[bold cyan]📂 远程路径:[/bold cyan] {remote_path_display}\n"
                host_display += f"[bold cyan]🌐 项目首页:[/bold cyan] {cname_domain if cname_domain else '[yellow]为配置[/]'}"
            else:
                host_display = f"[bold cyan]🖥️ 远程主机:[/bold cyan] [yellow]为配置[/]\n"
                host_display += f"[bold cyan]🌐 项目首页:[/bold cyan] {cname_domain if cname_domain else '[yellow]为配置[/]'}"

            # 构造合并后的面板内容
            menu_content = f"[bold cyan]📂 项目路径:\n[/bold cyan] [bold green]{project_path}[/bold green]\n"
            menu_content += f"[dim]─[/dim]" * 60 + "\n"
            menu_content += f"{host_display}\n"
            menu_content += "[dim]─[/dim]" * 60 + "\n"
            
            options = [
                "🔄 智能同步 [dim]自动判断同步更新双端数据[/dim]", 
                "📤 [magenta]强制推送[/magenta] [dim]强制推送本地数据到云端[/dim]", 
                "📥 [magenta]强制拉取[/magenta] [dim]强制拉取云端数据到本地[/dim]", 
                "🔎 本地预览 [dim]在浏览器中预览本地项目文件[/dim]",
                "🔍 远程预览 [dim]预览远程主机文件树形结构[/dim]",
                "⚙️ 主机配置 [dim]添加/更新远程主机连接信息(server.json)[/dim]",
                "🌐 首页配置 [dim]添加/更新项目主页(CNAME)[/dim]",
                "🔗 生成链接 [dim]生成项目文件访问链接(link.md)[/dim]", 
                "📂 切换项目 [dim]切换当前项目路径[/dim]", 
                "🚪 退出脚本"
            ]
            
            for i, option in enumerate(options):
                idx = i + 1 if "退出" not in option else 0
                menu_content += f"[bold blue]{idx}.[/bold blue] {option}\n"
            
            from rich.panel import Panel
            console.print(Panel(menu_content.strip(), title=f"[bold cyan]🚀 {menu_title}[/bold cyan]", border_style="cyan", expand=False))
            
            choice = ask_input("请选择操作 (0-9)")
            
            if choice == "1":
                # 智能同步
                print_step("正在执行智能同步...")
                try:
                    spec = get_ignore_spec(project_path)
                    from src.sync import smart_sync
                    if smart_sync(project_path, spec):
                        from src.ui import ask_confirm
                        if ask_confirm("同步完成，是否立即生成文件链接?"):
                            generate_links_workflow(project_path)
                except Exception as e:
                    print_error(f"同步失败: {e}")
                input("\n按回车键继续...")
            
            elif choice == "2":
                # 强制上传
                print_step("准备强制上传到远程...")
                try:
                    spec = get_ignore_spec(project_path)
                    from src.sync import sync_to_remote
                    if sync_to_remote(project_path, spec, force=True):
                        from src.ui import ask_confirm
                        if ask_confirm("同步完成，是否立即生成文件链接?"):
                            generate_links_workflow(project_path)
                except Exception as e:
                    print_error(f"上传失败: {e}")
                input("\n按回车键继续...")
                
            elif choice == "3":
                # 强制下载
                print_step("准备从远程强制下载...")
                try:
                    spec = get_ignore_spec(project_path)
                    from src.sync import sync_from_remote
                    if sync_from_remote(project_path, spec, force=True):
                        from src.ui import ask_confirm
                        if ask_confirm("同步完成，是否立即生成文件链接?"):
                            generate_links_workflow(project_path)
                except Exception as e:
                    print_error(f"下载失败: {e}")
                input("\n按回车键继续...")

            elif choice == "4":
                # 本地预览
                config = load_config()
                port = config.get("preview_port", 8000)
                if preview_manager.start(project_path, port):
                    print_info("按回车键停止预览并退出...")
                    input("\n按回车键继续...")
                    preview_manager.stop()
                else:
                    input("\n按回车键继续...")
            
            elif choice == "5":
                # 远程预览
                from src.sync import preview_remote_structure
                preview_remote_structure(project_path)
                input("\n按回车键继续...")
                
            elif choice == "6":
                # 主机配置
                from src.sync import manage_host_config
                manage_host_config(project_path)
                input("\n按回车键继续...")

            elif choice == "7":
                # 首页配置
                from src.site_info import manage_domain_config
                manage_domain_config(project_path)
                input("\n按回车键继续...")

            elif choice == "8":
                # 生成链接
                try:
                    generate_links_workflow(project_path)
                except Exception as e:
                    print_error(f"生成链接失败: {e}")
                input("\n按回车键继续...")

            elif choice == "9":
                # 切换项目
                project_path = select_project_workflow()
                
            elif choice == "0":
                preview_manager.stop()
                print_info("退出脚本，再见！")
                break
            else:
                print_error("无效的选择，请重新输入。")
                input("\n按回车键继续...")

    except KeyboardInterrupt:
        preview_manager.stop()
        print_info("已取消操作，退出脚本。")
    except Exception as e:
        print_error(f"发生意外错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
