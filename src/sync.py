import os
import json
import ftplib
import stat
import time
from pathlib import Path
import pathspec
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TransferSpeedColumn
from rich.panel import Panel
from rich.table import Table
from src.ui import print_info, print_success, print_error, print_warning, print_step, print_server_info, ask_confirm, console
from src.filter import is_ignored

# --- 辅助函数 ---

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
            structure[rel_path] = {"type": "file", "size": item.stat().st_size}
    return structure

def get_remote_structure_ftp(ftp, current_remote, base_remote):
    """递归获取 FTP 远程结构"""
    structure = {}
    current_remote = normalize_path(current_remote)
    base_remote = normalize_path(base_remote)
    
    try:
        try:
            # 优先使用 mlsd
            for name, facts in ftp.mlsd(current_remote):
                if name in (".", ".."): continue
                remote_item_path = normalize_path(f"{current_remote}/{name}")
                # 计算相对路径
                rel_path = remote_item_path[len(base_remote):].lstrip("/")
                
                if facts['type'] == 'dir':
                    structure[rel_path] = {"type": "dir", "size": 0}
                    structure.update(get_remote_structure_ftp(ftp, remote_item_path, base_remote))
                else:
                    structure[rel_path] = {"type": "file", "size": int(facts.get('size', 0))}
            return structure
        except:
            items = ftp.nlst(current_remote)
            for item_path in items:
                name = Path(item_path).name
                if name in (".", ".."): continue
                remote_item_path = normalize_path(item_path if item_path.startswith("/") else f"{current_remote}/{name}")
                rel_path = remote_item_path[len(base_remote):].lstrip("/")
                
                is_dir = False
                size = 0
                try:
                    size = ftp.size(remote_item_path)
                    if size is None: is_dir = True
                except:
                    is_dir = True
                
                if is_dir:
                    structure[rel_path] = {"type": "dir", "size": 0}
                    structure.update(get_remote_structure_ftp(ftp, remote_item_path, base_remote))
                else:
                    structure[rel_path] = {"type": "file", "size": size or 0}
    except:
        pass
    return structure

def get_remote_structure_sftp(sftp, current_remote, base_remote):
    """递归获取 SFTP 远程结构"""
    structure = {}
    try:
        for item in sftp.listdir_attr(current_remote):
            if item.filename in (".", ".."): continue
            remote_item_path = normalize_path(f"{current_remote}/{item.filename}")
            rel_path = remote_item_path[len(base_remote):].lstrip("/")
            
            if stat.S_ISDIR(item.st_mode):
                structure[rel_path] = {"type": "dir", "size": 0}
                structure.update(get_remote_structure_sftp(sftp, remote_item_path, base_remote))
            else:
                structure[rel_path] = {"type": "file", "size": item.st_size}
    except:
        pass
    return structure

# --- 同步计划 ---

def generate_sync_plan(local_struct, remote_struct):
    """对比两端结构，生成同步计划"""
    all_paths = sorted(list(set(local_struct.keys()) | set(remote_struct.keys())))
    plan = {"upload": [], "delete": [], "skip": []}
    stats = {"added": 0, "updated": 0, "deleted": 0}
    
    path_states = {}
    for path in all_paths:
        if path in local_struct and path not in remote_struct:
            plan["upload"].append(path)
            path_states[path] = "added"
            if local_struct[path]["type"] == "file": stats["added"] += 1
        elif path not in local_struct and path in remote_struct:
            plan["delete"].append(path)
            path_states[path] = "deleted"
            if remote_struct[path]["type"] == "file": stats["deleted"] += 1
        elif path in local_struct and path in remote_struct:
            if local_struct[path]["type"] == "dir":
                plan["skip"].append(path)
                path_states[path] = "none"
            elif local_struct[path]["size"] == remote_struct[path]["size"]:
                plan["skip"].append(path)
                path_states[path] = "none"
            else:
                plan["upload"].append(path)
                path_states[path] = "updated"
                stats["updated"] += 1
                
    return plan, path_states, stats

def display_sync_tree(path_states, local_struct, remote_struct, project_name, stats):
    """显示优化的同步预览树"""
    from rich.tree import Tree
    summary = f"[bold green]+ {stats['added']} 待同步[/bold green]  " \
              f"[bold yellow]~ {stats['updated']} 待更新[/bold yellow]  " \
              f"[bold red]- {stats['deleted']} 待删除[/bold red]"
    console.print(Panel(summary, title="📊 同步摘要", expand=False))
    
    tree = Tree(f"[bold blue]📁 {project_name}[/bold blue]")
    nodes = {"": tree}
    all_paths = sorted(path_states.keys())
    
    for path in all_paths:
        parts = path.split("/")
        parent = "/".join(parts[:-1])
        name = parts[-1]
        
        state = path_states[path]
        style, label = "dim", ""
        
        if state == "added":
            style, label = "bold green", "[待同步]"
        elif state == "deleted":
            style, label = "bold red", "[待删除]"
        elif state == "updated":
            style, label = "bold yellow", "[待更新]"
            
        if parent in path_states and path_states[parent] in ("added", "deleted"):
            label = ""
            
        icon = "📁" if (local_struct.get(path) or remote_struct.get(path))["type"] == "dir" else "📄"
        display_text = f"[{style}]{icon} {name} {label}[/{style}]"
        
        if parent in nodes:
            nodes[path] = nodes[parent].add(display_text)
            
    console.print(tree)

# --- 执行函数 ---

def sync_files(project_path: Path, spec: pathspec.PathSpec):
    server_json = project_path / "server.json"
    if not server_json.exists():
        print_error("未找到 server.json")
        return False
    
    try:
        with open(server_json, "r", encoding="utf-8") as f:
            config_all = json.load(f)
        protocol = "ftp" if "ftp" in config_all else "sftp" if "sftp" in config_all else None
        config = config_all[protocol]
    except Exception as e:
        print_error(f"配置文件解析失败: {e}")
        return False

    print_server_info(protocol, config)
    
    local_struct, remote_struct = {}, {}
    with console.status("[bold cyan]正在分析同步计划...[/bold cyan]", spinner="dots"):
        local_struct = get_local_structure(project_path, project_path, spec)
        try:
            if protocol == "ftp":
                with ftplib.FTP() as ftp:
                    ftp.set_pasv(True)
                    ftp.connect(config["host"], config.get("port", 21), timeout=30)
                    ftp.login(config["user"], config["password"])
                    base = normalize_path(config.get("remote_path") or ftp.pwd())
                    remote_struct = get_remote_structure_ftp(ftp, base, base)
            else:
                import paramiko
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(config["host"], config.get("port", 22), config["user"], config["password"])
                sftp = ssh.open_sftp()
                base = normalize_path(config.get("remote_path") or sftp.normalize("."))
                remote_struct = get_remote_structure_sftp(sftp, base, base)
                sftp.close(); ssh.close()
        except Exception as e:
            print_warning(f"分析远程结构时遇到问题: {e}")

    plan, path_states, stats = generate_sync_plan(local_struct, remote_struct)
    display_sync_tree(path_states, local_struct, remote_struct, project_path.name, stats)
    
    if not (plan["upload"] or plan["delete"]):
        print_success("本地与远程完全一致，无需操作。")
        return False

    if not ask_confirm("确认执行上述同步计划吗?"):
        print_warning("已取消同步操作。")
        return False

    try:
        if protocol == "ftp":
            run_ftp_plan(project_path, config, plan)
        else:
            run_sftp_plan(project_path, config, plan)
        return True
    except Exception as e:
        print_error(f"同步失败: {e}")
        return False

def run_ftp_plan(project_root, config, plan):
    with ftplib.FTP() as ftp:
        ftp.set_pasv(True)
        ftp.connect(config["host"], config.get("port", 21), timeout=60)
        ftp.login(config["user"], config["password"])
        base = normalize_path(config.get("remote_path") or ftp.pwd())
        
        if plan["upload"]:
            print_step("正在上传文件...")
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TransferSpeedColumn(),
                console=console
            ) as progress:
                for path in plan["upload"]:
                    local_file = project_root / path
                    remote_file = normalize_path(f"{base}/{path}")
                    if local_file.is_dir():
                        try: ftp.mkd(remote_file)
                        except: pass
                    else:
                        task = progress.add_task(f"上传 {path}", total=local_file.stat().st_size)
                        ensure_remote_dir_ftp(ftp, normalize_path(os.path.dirname(remote_file)))
                        with open(local_file, "rb") as f:
                            ftp.storbinary(f"STOR {remote_file}", f, callback=lambda chunk: progress.update(task, advance=len(chunk)))
                        progress.remove_task(task)
        
    if plan["delete"]:
        print_step("正在清理远程多余文件...")
        try:
            with ftplib.FTP() as ftp:
                ftp.set_pasv(True)
                ftp.connect(config["host"], config.get("port", 21), timeout=60)
                ftp.login(config["user"], config["password"])
                base = normalize_path(config.get("remote_path") or ftp.pwd())
                for path in reversed(plan["delete"]):
                    remote_item = normalize_path(f"{base}/{path}")
                    try:
                        ftp.delete(remote_item)
                        print_warning(f"已删除: {path}")
                    except:
                        try:
                            ftp.rmd(remote_item)
                            print_warning(f"已删除目录: {path}")
                        except:
                            pass
        except Exception as e:
            print_error(f"清理阶段连接失败: {e}")
                    
    print_success("FTP 同步完成！")

def run_sftp_plan(project_root, config, plan):
    import paramiko
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(config["host"], config.get("port", 22), config["user"], config["password"])
    sftp = ssh.open_sftp()
    base = normalize_path(config.get("remote_path") or sftp.normalize("."))
    
    if plan["upload"]:
        print_step("正在上传文件...")
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TransferSpeedColumn(),
            console=console
        ) as progress:
            for path in plan["upload"]:
                local_file = project_root / path
                remote_file = normalize_path(f"{base}/{path}")
                if local_file.is_dir():
                    try: sftp.mkdir(remote_file)
                    except: pass
                else:
                    task = progress.add_task(f"上传 {path}", total=local_file.stat().st_size)
                    ensure_remote_dir_sftp(sftp, normalize_path(os.path.dirname(remote_file)))
                    sftp.put(str(local_file), remote_file, callback=lambda cur, tot: progress.update(task, completed=cur))
                    progress.remove_task(task)
            
    if plan["delete"]:
        print_step("正在清理远程多余文件...")
        for path in reversed(plan["delete"]):
            remote_item = normalize_path(f"{base}/{path}")
            try:
                sftp.remove(remote_item)
                print_warning(f"已删除: {path}")
            except:
                try:
                    sftp.rmdir(remote_item)
                    print_warning(f"已删除目录: {path}")
                except:
                    pass
                
    sftp.close(); ssh.close()
    print_success("SFTP 同步完成！")

def ensure_remote_dir_ftp(ftp, path):
    if path == "/": return
    parts = path.strip("/").split("/")
    curr = ""
    for p in parts:
        curr += "/" + p
        try:
            ftp.mkd(curr)
        except:
            pass

def ensure_remote_dir_sftp(sftp, path):
    if path == "/": return
    parts = path.strip("/").split("/")
    curr = ""
    for p in parts:
        curr += "/" + p
        try:
            sftp.mkdir(curr)
        except:
            pass
