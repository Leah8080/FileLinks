import os
import json
import ftplib
import stat
import time
from pathlib import Path
import pathspec
import shutil
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TransferSpeedColumn
from rich.panel import Panel
from rich.table import Table
from src.ui import print_info, print_success, print_error, print_warning, print_step, print_server_info, ask_confirm, ask_input, console
from src.filter import is_ignored

import hashlib
import concurrent.futures

# --- 辅助函数 ---

SYNC_STATE_FILENAME = ".sync_state"
SYNC_LOG_FILENAME = ".sync_log"

def calculate_md5(file_path: Path) -> str:
    """计算本地文件的 MD5 校验和"""
    hash_md5 = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except Exception:
        return ""

def load_sync_state(project_path: Path) -> dict:
    """加载本地同步状态缓存"""
    state_file = project_path / SYNC_STATE_FILENAME
    if state_file.exists():
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_sync_state(project_path: Path, state: dict):
    """保存当前同步状态到本地"""
    state_file = project_path / SYNC_STATE_FILENAME
    try:
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print_warning(f"无法保存同步状态缓存: {e}")

def normalize_path(path_str):
    """确保路径使用正斜杠，且不带末尾斜杠。保留起始斜杠以维持绝对路径性质。"""
    if not path_str: return "/"
    p = path_str.replace("\\", "/").strip("/")
    return "/" + p if p else "/"

def get_local_structure(path: Path, project_root: Path, spec):
    """递归获取本地文件结构"""
    structure = {}
    for item in path.iterdir():
        if is_ignored(item, project_root, spec, item.is_dir()):
            continue
        
        rel_path = item.relative_to(project_root).as_posix().strip("/")
        if item.is_dir():
            structure[rel_path] = {"type": "dir", "size": 0}
            structure.update(get_local_structure(item, project_root, spec))
        else:
            structure[rel_path] = {
                "type": "file",
                "size": item.stat().st_size,
                "md5": calculate_md5(item)
            }
    return structure

# --- 远程状态与清理 ---

def fetch_remote_state(protocol, config):
    """从远程下载 .sync_state 并解析"""
    try:
        if protocol == "ftp":
            with ftplib.FTP() as ftp:
                ftp.set_pasv(True)
                ftp.connect(config["host"], config.get("port", 21), timeout=15)
                ftp.login(config["user"], config["password"])
                base = normalize_path(config.get("remote_path") or ftp.pwd())
                remote_file = f"{base}/{SYNC_STATE_FILENAME}"
                
                content = []
                try:
                    ftp.retrbinary(f"RETR {remote_file}", callback=content.append)
                    return json.loads(b"".join(content).decode("utf-8"))
                except:
                    return None
        else:
            import paramiko
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(config["host"], config.get("port", 22), config["user"], config["password"], timeout=15)
            sftp = ssh.open_sftp()
            base = normalize_path(config.get("remote_path") or sftp.normalize("."))
            remote_file = f"{base}/{SYNC_STATE_FILENAME}"
            
            try:
                with sftp.open(remote_file, "r") as f:
                    return json.load(f)
            except:
                return None
            finally:
                sftp.close(); ssh.close()
    except:
        return None

def push_remote_state(protocol, config, state):
    """将状态字典上传到远程作为 .sync_state"""
    state_json = json.dumps(state, indent=2, ensure_ascii=False)
    try:
        if protocol == "ftp":
            with ftplib.FTP() as ftp:
                ftp.set_pasv(True)
                ftp.connect(config["host"], config.get("port", 21), timeout=15)
                ftp.login(config["user"], config["password"])
                base = normalize_path(config.get("remote_path") or ftp.pwd())
                remote_file = f"{base}/{SYNC_STATE_FILENAME}"
                
                import io
                bio = io.BytesIO(state_json.encode("utf-8"))
                ftp.storbinary(f"STOR {remote_file}", bio)
        else:
            import paramiko
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(config["host"], config.get("port", 22), config["user"], config["password"], timeout=15)
            sftp = ssh.open_sftp()
            base = normalize_path(config.get("remote_path") or sftp.normalize("."))
            remote_file = f"{base}/{SYNC_STATE_FILENAME}"
            
            with sftp.open(remote_file, "w") as f:
                f.write(state_json)
            sftp.close(); ssh.close()
    except Exception as e:
        print_warning(f"无法同步状态到云端: {e}")

def wipe_remote(protocol, config):
    """完全清空远程目录"""
    def ftp_remove_dir(ftp, path):
        for name, facts in ftp.mlsd(path):
            if name in (".", ".."): continue
            full_path = f"{path}/{name}"
            if facts['type'] == 'dir':
                ftp_remove_dir(ftp, full_path)
            else:
                ftp.delete(full_path)
        ftp.rmd(path)

    def sftp_remove_dir(sftp, path):
        for item in sftp.listdir_attr(path):
            if item.filename in (".", ".."): continue
            full_path = f"{path}/{item.filename}"
            if stat.S_ISDIR(item.st_mode):
                sftp_remove_dir(sftp, full_path)
            else:
                sftp.remove(full_path)
        sftp.rmdir(path)

    try:
        if protocol == "ftp":
            with ftplib.FTP() as ftp:
                ftp.set_pasv(True)
                ftp.connect(config["host"], config.get("port", 21), timeout=30)
                ftp.login(config["user"], config["password"])
                base = normalize_path(config.get("remote_path") or ftp.pwd())
                print_step(f"正在清空远程目录: {base}")
                for name, facts in ftp.mlsd(base):
                    if name in (".", ".."): continue
                    full_path = f"{base}/{name}"
                    if facts['type'] == 'dir':
                        ftp_remove_dir(ftp, full_path)
                    else:
                        ftp.delete(full_path)
        else:
            import paramiko
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(config["host"], config.get("port", 22), config["user"], config["password"])
            sftp = ssh.open_sftp()
            base = normalize_path(config.get("remote_path") or sftp.normalize("."))
            print_step(f"正在清空远程目录: {base}")
            for item in sftp.listdir_attr(base):
                if item.filename in (".", ".."): continue
                full_path = f"{base}/{item.filename}"
                if stat.S_ISDIR(item.st_mode):
                    sftp_remove_dir(sftp, full_path)
                else:
                    sftp.remove(full_path)
            sftp.close(); ssh.close()
        return True
    except Exception as e:
        print_error(f"清空远程目录失败: {e}")
        return False

# --- 同步逻辑 ---

def generate_sync_plan(source_struct, target_struct, cache_struct=None, base_struct=None):
    """
    对比两端结构，生成同步计划。
    base_struct: 上次同步时的状态，用于冲突检测。
    """
    if cache_struct is None: cache_struct = {}
    if base_struct is None: base_struct = {}
    
    all_paths = sorted(list(set(source_struct.keys()) | set(target_struct.keys())))
    plan = {"upload": [], "delete": [], "skip": [], "conflict": []}
    stats = {"added": 0, "updated": 0, "deleted": 0, "conflict": 0}
    path_states = {}
    
    for path in all_paths:
        # 基础冲突检测逻辑：
        # 如果 source 和 target 都相对于 base 发生了变化，且变化结果不同，则为冲突。
        is_source_changed = False
        is_target_changed = False
        
        if path in source_struct:
            if path not in base_struct: is_source_changed = True
            elif source_struct[path].get("md5") != base_struct[path].get("md5"): is_source_changed = True
            elif source_struct[path].get("size") != base_struct[path].get("size"): is_source_changed = True
            
        if path in target_struct:
            if path not in base_struct: is_target_changed = True
            elif target_struct[path].get("md5") != base_struct[path].get("md5"): is_target_changed = True
            elif target_struct[path].get("size") != base_struct[path].get("size"): is_target_changed = True
            
        # 路径删除也被视为变化
        if path in base_struct and path not in source_struct: is_source_changed = True
        if path in base_struct and path not in target_struct: is_target_changed = True

        if is_source_changed and is_target_changed:
            # 进一步判断是否真的冲突（比如两边改成了同样的内容，则不算冲突）
            content_match = False
            if path in source_struct and path in target_struct:
                if source_struct[path].get("md5") == target_struct[path].get("md5") and \
                   source_struct[path].get("size") == target_struct[path].get("size"):
                    content_match = True
            elif path not in source_struct and path not in target_struct:
                content_match = True
                
            if not content_match:
                plan["conflict"].append(path)
                path_states[path] = "conflict"
                stats["conflict"] += 1
                continue

        # 正常的增量判断
        if path in source_struct and path not in target_struct:
            plan["upload"].append(path)
            path_states[path] = "added"
            if source_struct[path]["type"] == "file": stats["added"] += 1
        elif path not in source_struct and path in target_struct:
            plan["delete"].append(path)
            path_states[path] = "deleted"
            if target_struct[path]["type"] == "file": stats["deleted"] += 1
        elif path in source_struct and path in target_struct:
            if source_struct[path]["type"] == "dir":
                plan["skip"].append(path)
                path_states[path] = "none"
            else:
                is_modified = False
                if source_struct[path]["size"] != target_struct[path]["size"]:
                    is_modified = True
                else:
                    s_md5 = source_struct[path].get("md5")
                    t_md5 = target_struct[path].get("md5")
                    if s_md5 and t_md5 and s_md5 != t_md5:
                        is_modified = True
                    elif s_md5 and not t_md5:
                        c_md5 = cache_struct.get(path, {}).get("md5")
                        if c_md5 and s_md5 != c_md5:
                            is_modified = True
                
                if is_modified:
                    plan["upload"].append(path)
                    path_states[path] = "updated"
                    stats["updated"] += 1
                else:
                    plan["skip"].append(path)
                    path_states[path] = "none"
                
    return plan, path_states, stats

def display_sync_tree(path_states, source_struct, target_struct, project_name, stats, is_download=False):
    """显示优化的同步预览树"""
    from rich.tree import Tree
    action_text = "下载" if is_download else "上传"
    summary = f"[bold green]+ {stats['added']} 待{action_text}[/bold green]  " \
              f"[bold yellow]~ {stats['updated']} 待更新[/bold yellow]  " \
              f"[bold red]- {stats['deleted']} 待删除[/bold red]"
    if stats.get("conflict"):
        summary += f"  [bold magenta]! {stats['conflict']} 冲突[/bold magenta]"
        
    console.print(Panel(summary, title="📊 同步摘要", expand=False))
    
    tree = Tree(f"[bold blue]📁 {project_name}[/bold blue]")
    nodes = {"": tree}
    all_paths = sorted(path_states.keys())
    
    from src.config_loader import load_config
    config = load_config()
    icon_map = config.get("icons", {})

    for path in all_paths:
        parts = path.split("/")
        parent = "/".join(parts[:-1])
        name = parts[-1]
        
        state = path_states[path]
        
        # 始终完整显示，不再根据 has_changes 进行过滤
        style, label = "dim", ""
        if state == "added":
            style, label = "bold green", f"[待{action_text}]"
        elif state == "deleted":
            style, label = "bold red", "[待删除]"
        elif state == "updated":
            style, label = "bold yellow", "[待更新]"
        elif state == "conflict":
            style, label = "bold magenta", "[冲突]"
            
        is_dir = (source_struct.get(path) or target_struct.get(path))["type"] == "dir"
        
        if is_dir:
            icon = "📁"
        else:
            # 根据扩展名获取图标
            ext = Path(name).suffix.lower()
            icon = icon_map.get(ext, "📄")
        
        # 根据状态为文件名也添加颜色
        display_text = f"[{style}]{icon} {name} {label}[/{style}]"
        
        if parent in nodes:
            nodes[path] = nodes[parent].add(display_text)
            
    console.print(tree)

# --- 工作流 ---

def smart_sync(project_path: Path, spec: pathspec.PathSpec):
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

    # 2. 如果只有一方有状态，或者状态不一致，计算差异
    # 智能同步的逻辑：优先以上传本地改动为主，但如果云端有更新，则提示
    print_info("正在分析增量更新...")
    
    # 获取真正的远程结构以防状态文件过时
    if not remote_state:
        with console.status("[cyan]正在扫描远程结构..."):
            remote_state = get_real_remote_structure(protocol, cfg)

    # 这里的智能逻辑可以更复杂，目前先实现一个稳妥的：
    # 对比本地 vs 记录，对比云端 vs 记录
    # 如果只有一侧变了，自动处理；如果两侧都变了，提示冲突。
    
    # 简化版：目前先按“同步本地”的增强版处理
    return sync_to_remote(project_path, spec, force=False)

def sync_to_remote(project_path: Path, spec: pathspec.PathSpec, force=False):
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

    # 增量上传逻辑
    if not local_state:
        print_warning("本地无同步记录。请使用“强制上传”或先执行“强制下载”初始化状态。")
        return False

    if remote_state and remote_state != local_state:
        print_warning("⚠️ 远程状态已更新，本地记录已过时。")
        if not ask_confirm("仍要覆盖远程改动吗？"): return False

    target_for_plan = remote_state if remote_state else local_state
    plan, path_states, stats = generate_sync_plan(local_struct, target_for_plan, base_struct=local_state)
    
    # 无论是否有变动，都先显示树供预览
    display_sync_tree(path_states, local_struct, target_for_plan, project_path.name, stats)

    if stats.get("conflict"):
        print_warning(f"检测到 {stats['conflict']} 处冲突！")
        if not ask_confirm("冲突项将以本地为准进行覆盖，是否继续？"):
            return False
            
    if not (plan["upload"] or plan["delete"]):
        print_success("本地与远程已同步，无需操作。")
        return True

    confirm = ask_input("确认执行同步计划？([bold green]Y[/bold green]继续 / [bold yellow]P[/bold yellow]仅预览退出 / [bold red]N[/bold red]取消)").upper()
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

def sync_from_remote(project_path: Path, spec: pathspec.PathSpec, force=False):
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

# --- 执行底座 ---

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

def run_sync_action(project_root, config, protocol, plan, source_struct, is_download=False):
    """并发执行上传/下载逻辑"""
    failed_files = []
    
    def process_file(path):
        try:
            if protocol == "ftp":
                with ftplib.FTP() as ftp:
                    ftp.set_pasv(True)
                    ftp.connect(config["host"], config.get("port", 21), timeout=30)
                    ftp.login(config["user"], config["password"])
                    base = normalize_path(config.get("remote_path") or ftp.pwd())
                    local_file = project_root / path
                    remote_file = normalize_path(f"{base}/{path}")
                    is_dir = source_struct.get(path, {}).get("type") == "dir"
                    if is_download:
                        if is_dir: local_file.mkdir(parents=True, exist_ok=True)
                        else:
                            local_file.parent.mkdir(parents=True, exist_ok=True)
                            with open(local_file, "wb") as f:
                                ftp.retrbinary(f"RETR {remote_file}", f.write)
                    else:
                        if is_dir: 
                            try: ftp.mkd(remote_file)
                            except: pass
                        else:
                            with open(local_file, "rb") as f:
                                ftp.storbinary(f"STOR {remote_file}", f)
            else:
                import paramiko
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(config["host"], config.get("port", 22), config["user"], config["password"], timeout=30)
                sftp = ssh.open_sftp()
                base = normalize_path(config.get("remote_path") or sftp.normalize("."))
                local_file = project_root / path
                remote_file = normalize_path(f"{base}/{path}")
                is_dir = source_struct.get(path, {}).get("type") == "dir"
                if is_download:
                    if is_dir: local_file.mkdir(parents=True, exist_ok=True)
                    else:
                        local_file.parent.mkdir(parents=True, exist_ok=True)
                        sftp.get(remote_file, str(local_file))
                else:
                    if is_dir:
                        try: sftp.mkdir(remote_file)
                        except: pass
                    else:
                        sftp.put(str(local_file), remote_file)
                sftp.close(); ssh.close()
            return True, path
        except Exception as e:
            return False, (path, str(e))

    print_step(f"正在准备{'下载' if is_download else '上传'}队列...")
    dirs = [p for p in plan["upload"] if source_struct.get(p, {}).get("type") == "dir"]
    files = [p for p in plan["upload"] if source_struct.get(p, {}).get("type") != "dir"]
    
    if dirs:
        for d in dirs:
            success, res = process_file(d)
            if not success: failed_files.append(res)

    if files:
        from src.config_loader import load_config
        config_data = load_config()
        max_workers = config_data.get("max_workers", 3)
        
        action_name = "下载" if is_download else "上传"
        print_step(f"正在并发{action_name}文件 ({len(files)} 个, 并发数: {max_workers})...")
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), BarColumn(), TaskProgressColumn(), TransferSpeedColumn(), console=console, transient=True) as progress:
            task = progress.add_task(f"{action_name}中...", total=len(files))
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_path = {executor.submit(process_file, p): p for p in files}
                for future in concurrent.futures.as_completed(future_to_path):
                    success, result = future.result()
                    if not success: failed_files.append(result)
                    progress.update(task, advance=1)

    if plan["delete"]:
        print_step(f"正在清理{'本地' if is_download else '远程'}多余文件...")
        try:
            if protocol == "ftp":
                with ftplib.FTP() as ftp:
                    ftp.set_pasv(True)
                    ftp.connect(config["host"], config.get("port", 21), timeout=60)
                    ftp.login(config["user"], config["password"])
                    base = normalize_path(config.get("remote_path") or ftp.pwd())
                    for path in reversed(plan["delete"]):
                        try:
                            if is_download:
                                item = project_root / path
                                if item.is_file(): item.unlink()
                                elif item.is_dir(): shutil.rmtree(item)
                            else:
                                item = normalize_path(f"{base}/{path}")
                                try: ftp.delete(item)
                                except: ftp.rmd(item)
                        except Exception as e: failed_files.append((path, str(e)))
            else:
                import paramiko
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(config["host"], config.get("port", 22), config["user"], config["password"])
                sftp = ssh.open_sftp()
                base = normalize_path(config.get("remote_path") or sftp.normalize("."))
                for path in reversed(plan["delete"]):
                    try:
                        if is_download:
                            item = project_root / path
                            if item.is_file(): item.unlink()
                            elif item.is_dir(): shutil.rmtree(item)
                        else:
                            item = normalize_path(f"{base}/{path}")
                            try: sftp.remove(item)
                            except: sftp.rmdir(item)
                    except Exception as e: failed_files.append((path, str(e)))
                sftp.close(); ssh.close()
        except Exception as e:
            print_error(f"清理阶段失败: {e}")

    if failed_files:
        print_warning(f"\n⚠️ 操作完成，但有 {len(failed_files)} 个项处理失败。")
        return False
    return True

# --- 辅助工具 ---

def get_real_remote_structure(protocol, config):
    if protocol == "ftp":
        with ftplib.FTP() as ftp:
            ftp.set_pasv(True)
            ftp.connect(config["host"], config.get("port", 21), timeout=30)
            ftp.login(config["user"], config["password"])
            base = normalize_path(config.get("remote_path") or ftp.pwd())
            return get_remote_structure_ftp(ftp, base, base)
    else:
        import paramiko
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(config["host"], config.get("port", 22), config["user"], config["password"])
        sftp = ssh.open_sftp()
        base = normalize_path(config.get("remote_path") or sftp.normalize("."))
        struct = get_remote_structure_sftp(sftp, base, base)
        sftp.close(); ssh.close()
        return struct

def get_remote_structure_ftp(ftp, current_remote, base_remote):
    structure = {}
    try:
        for name, facts in ftp.mlsd(current_remote):
            if name in (".", "..", SYNC_STATE_FILENAME): continue
            rel_path = normalize_path(f"{current_remote}/{name}")[len(base_remote):].lstrip("/")
            if facts['type'] == 'dir':
                structure[rel_path] = {"type": "dir", "size": 0}
                structure.update(get_remote_structure_ftp(ftp, f"{current_remote}/{name}", base_remote))
            else:
                structure[rel_path] = {"type": "file", "size": int(facts.get('size', 0))}
    except: pass
    return structure

def get_remote_structure_sftp(sftp, current_remote, base_remote):
    structure = {}
    try:
        for item in sftp.listdir_attr(current_remote):
            if item.filename in (".", "..", SYNC_STATE_FILENAME): continue
            rel_path = normalize_path(f"{current_remote}/{item.filename}")[len(base_remote):].lstrip("/")
            if stat.S_ISDIR(item.st_mode):
                structure[rel_path] = {"type": "dir", "size": 0}
                structure.update(get_remote_structure_sftp(sftp, f"{current_remote}/{item.filename}", base_remote))
            else:
                structure[rel_path] = {"type": "file", "size": item.st_size}
    except: pass
    return structure

def ensure_remote_dir_ftp(ftp, path):
    if path == "/" or not path: return
    parts = path.strip("/").split("/")
    curr = ""
    for p in parts:
        curr += "/" + p
        try: ftp.mkd(curr)
        except: pass

def ensure_remote_dir_sftp(sftp, path):
    if path == "/" or not path: return
    parts = path.strip("/").split("/")
    curr = ""
    for p in parts:
        curr += "/" + p
        try: sftp.mkdir(curr)
        except: pass
