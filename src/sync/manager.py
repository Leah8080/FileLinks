import json
import time
from pathlib import Path
from src.ui import print_info, print_success, print_error, print_warning, print_step, ask_confirm, ask_input, console
from src.sync.scanner import get_local_structure, load_sync_state, save_sync_state, SYNC_LOG_FILENAME, normalize_path
from src.sync.engine import generate_sync_plan
from src.sync.comm import fetch_remote_state, push_remote_state, wipe_remote, run_sync_action, get_real_remote_structure
from src.sync.view import display_sync_tree, display_remote_tree

def get_server_config(project_path):
    server_json = project_path / "server.json"
    if not server_json.exists():
        return None
    try:
        with open(server_json, "r", encoding="utf-8") as f:
            config_all = json.load(f)
        protocol = "ftp" if "ftp" in config_all else "sftp" if "sftp" in config_all else None
        if not protocol: return None
        return protocol, config_all[protocol]
    except Exception:
        return None

def manage_host_config(project_path: Path):
    """交互式管理主机配置"""
    print_step("配置远程主机信息")
    current = get_server_config(project_path)
    
    # 默认值设置
    def_proto = "sftp"
    def_host, def_port, def_user, def_pass, def_path = "", "", "", "", "/"
    
    if current:
        def_proto, cfg = current
        def_host = cfg.get("host", "")
        def_port = str(cfg.get("port", ""))
        def_user = cfg.get("user", "")
        def_pass = cfg.get("password", "")
        def_path = cfg.get("remote_path", "/")

    print_info("提示：直接回车将保留默认值/当前值")
    
    proto = ask_input(f"传输协议 (ftp/sftp) [当前: [magenta]{def_proto}[/magenta]]") or def_proto
    proto = proto.lower()
    if proto not in ["ftp", "sftp"]:
        print_error("无效的协议，仅支持 ftp 或 sftp")
        return False
    
    if not def_port:
        def_port = "21" if proto == "ftp" else "22"
        
    host = ask_input(f"主机地址 [当前: [magenta]{def_host}[/magenta]]") or def_host
    port = ask_input(f"端口号 [当前: [magenta]{def_port}[/magenta]]") or def_port
    user = ask_input(f"账户 [当前: [magenta]{def_user}[/magenta]]") or def_user
    password = ask_input(f"密码 [当前: [magenta]{'******' if def_pass else '未设置'}[/magenta]]") or def_pass
    
    print_info(r"提示：翼龙面板(Pterodactyl)主机用户请将远程路径设为 / 或留空")
    remote_path = ask_input(f"远程路径 [当前: [magenta]{def_path}[/magenta]]\n⏳ 请输入") or def_path
    
    config_data = {
        proto: {
            "host": host,
            "port": int(port) if port.isdigit() else (21 if proto == "ftp" else 22),
            "user": user,
            "password": password,
            "remote_path": normalize_path(remote_path)
        }
    }
    
    try:
        with open(project_path / "server.json", "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4, ensure_ascii=False)
        print_success("主机配置已保存到 server.json")
        return True
    except Exception as e:
        print_error(f"保存配置失败: {e}")
        return False

def log_action(project_path: Path, action_type: str, stats: dict):
    """记录同步操作到 .sync_log"""
    log_file = project_path / SYNC_LOG_FILENAME
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {action_type}: +{stats.get('added', 0)} added, ~{stats.get('updated', 0)} updated, -{stats.get('deleted', 0)} deleted\n"
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except Exception:
        pass

def smart_sync(project_path: Path, spec):
    """智能同步：自动判断增量更新"""
    config = get_server_config(project_path)
    if not config: return False
    protocol, cfg = config

    local_struct = get_local_structure(project_path, project_path, spec)
    local_state = load_sync_state(project_path)
    remote_state = fetch_remote_state(protocol, cfg)

    # 1. 如果两边都没有状态，引导首次同步
    if not local_state and not remote_state:
        print_warning("检测到首次同步。")
        choice = ask_input("是以本地为准[bold green]上传(U)[/bold green]，还是以云端为准[bold cyan]下载(D)[/bold cyan]？(U/D)")
        if choice.upper() == 'U':
            return sync_to_remote(project_path, spec, force=True)
        elif choice.upper() == 'D':
            return sync_from_remote(project_path, spec, force=True)
        return False

    print_info("正在分析增量更新...")
    
    if not remote_state:
        with console.status("[cyan]正在扫描远程结构..."):
            remote_state = get_real_remote_structure(protocol, cfg)

    return sync_to_remote(project_path, spec, force=False)

def sync_to_remote(project_path: Path, spec, force=False):
    config = get_server_config(project_path)
    if not config: return False
    protocol, cfg = config

    local_struct = get_local_structure(project_path, project_path, spec)
    local_state = load_sync_state(project_path)
    remote_state = fetch_remote_state(protocol, cfg)

    if force:
        print_warning("⚠️ [bold red]强制上传模式[/bold red]：将以本地文件为准，覆盖远程内容。")
        if not ask_confirm("确认清空远程并重新上传吗？"): return False
        if wipe_remote(protocol, cfg):
            plan = {"upload": sorted(local_struct.keys()), "delete": [], "skip": []}
            if run_sync_action(project_path, cfg, protocol, plan, local_struct, is_download=False):
                save_sync_state(project_path, local_struct)
                push_remote_state(protocol, cfg, local_struct)
                log_action(project_path, "Force Upload", {"added": len(local_struct)})
                print_success("首次同步完成！")
                return True
        return False

    if not local_state:
        print_warning("本地无同步记录。请使用“强制上传”或先执行“强制下载”初始化状态。")
        return False

    if remote_state and remote_state != local_state:
        print_warning("⚠️ 远程状态已更新，本地记录已过时。")
        if not ask_confirm("仍要覆盖远程改动吗？"): return False

    target_for_plan = remote_state if remote_state else local_state
    plan, path_states, stats = generate_sync_plan(local_struct, target_for_plan, base_struct=local_state)
    
    display_sync_tree(path_states, local_struct, target_for_plan, project_path.name, stats)

    if stats.get("conflict"):
        print_warning(f"检测到 {stats['conflict']} 处冲突！")
        if not ask_confirm("冲突项将以本地为准进行覆盖，是否继续？"):
            return False
            
    if not (plan["upload"] or plan["delete"]):
        print_success("本地与远程已同步，无需操作。")
        return True

    confirm = ask_input("确认执行同步计划？([bold green]Y[/bold green]确定 / [bold yellow]P[/bold yellow]仅预览 / [bold red]N[/bold red]取消)").upper()
    if confirm == 'Y':
        if run_sync_action(project_path, cfg, protocol, plan, local_struct, is_download=False):
            save_sync_state(project_path, local_struct)
            push_remote_state(protocol, cfg, local_struct)
            log_action(project_path, "Incremental Sync", stats)
            print_success("同步成功！")
            return True
    elif confirm == 'P':
        print_info("预览结束，未执行任何操作。")
        return False
    return False

def sync_from_remote(project_path: Path, spec, force=False):
    config = get_server_config(project_path)
    if not config: return False
    protocol, cfg = config

    local_state = load_sync_state(project_path)
    remote_state = fetch_remote_state(protocol, cfg)
    
    if not remote_state:
        with console.status("[cyan]扫描远程结构..."):
            remote_state = get_real_remote_structure(protocol, cfg)

    if force:
        print_warning("⚠️ [bold red]强制下载模式[/bold red]：将以云端文件为准，覆盖本地内容。")
        if not ask_confirm("确认同步云端到本地吗？(本地多余文件将被删除)"): return False
        local_struct = get_local_structure(project_path, project_path, spec)
        plan, path_states, stats = generate_sync_plan(remote_state, local_struct, local_state)
    else:
        if not local_state:
            print_warning("本地无记录，请使用“强制下载”。")
            return False
        local_struct = get_local_structure(project_path, project_path, spec)
        plan, path_states, stats = generate_sync_plan(remote_state, local_struct, local_state)

    display_sync_tree(path_states, remote_state, local_struct, project_path.name, stats, is_download=True)

    if not (plan["upload"] or plan["delete"]):
        print_success("本地已是最新，无需操作。")
        save_sync_state(project_path, remote_state)
        return True

    if ask_confirm("确认同步？"):
        if run_sync_action(project_path, cfg, protocol, plan, remote_state, is_download=True):
            new_local = get_local_structure(project_path, project_path, spec)
            save_sync_state(project_path, new_local)
            push_remote_state(protocol, cfg, new_local)
            return True
    return False

def preview_remote_structure(project_path: Path):
    """获取并显示远程主机的文件树预览"""
    config = get_server_config(project_path)
    if not config:
        print_error("未配置远程主机信息，请先进行“主机配置”。")
        return False
    
    protocol, cfg = config
    print_step(f"正在连接远程主机 ({protocol.upper()}) 并获取文件树...")
    
    try:
        with console.status("[cyan]正在扫描远程文件系统..."):
            remote_struct = get_real_remote_structure(protocol, cfg)
        
        if not remote_struct:
            print_warning("远程目录为空或无法读取。")
            return True
        
        display_remote_tree(remote_struct, project_path.name)
        return True
    except Exception as e:
        print_error(f"无法获取远程结构: {e}")
        return False
