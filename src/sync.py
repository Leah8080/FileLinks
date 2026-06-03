import os
import json
import ftplib
import stat
from pathlib import Path
import pathspec
from src.ui import print_info, print_success, print_error, print_warning, print_step, print_server_info, ask_confirm, console
from src.filter import is_ignored

# --- 结构分析函数 ---

def get_local_structure(path: Path, project_root: Path, spec):
    """递归获取本地文件结构"""
    structure = {}
    for item in path.iterdir():
        if is_ignored(item, project_root, spec, item.is_dir()):
            continue
        
        rel_path = item.relative_to(project_root).as_posix()
        if item.is_dir():
            structure[rel_path] = {"type": "dir", "size": 0}
            structure.update(get_local_structure(item, project_root, spec))
        else:
            structure[rel_path] = {"type": "file", "size": item.stat().st_size}
    return structure

def get_remote_structure_ftp(ftp, current_remote, base_remote):
    """递归获取 FTP 远程结构 (优化版)"""
    structure = {}
    try:
        try:
            for name, facts in ftp.mlsd(current_remote):
                if name in (".", ".."): continue
                remote_item_path = (Path(current_remote) / name).as_posix()
                rel_path = Path(remote_item_path).relative_to(base_remote).as_posix()
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
                remote_item_path = item_path if item_path.startswith("/") else (Path(current_remote) / name).as_posix()
                rel_path = Path(remote_item_path).relative_to(base_remote).as_posix()
                is_dir = False
                size = 0
                try:
                    size = ftp.size(remote_item_path) or 0
                except:
                    is_dir = True
                if is_dir:
                    structure[rel_path] = {"type": "dir", "size": 0}
                    structure.update(get_remote_structure_ftp(ftp, remote_item_path, base_remote))
                else:
                    structure[rel_path] = {"type": "file", "size": size}
    except:
        pass
    return structure

def get_remote_structure_sftp(sftp, current_remote, base_remote):
    """递归获取 SFTP 远程结构"""
    structure = {}
    try:
        for item in sftp.listdir_attr(current_remote):
            if item.filename in (".", ".."): continue
            remote_item_path = (Path(current_remote) / item.filename).as_posix()
            rel_path = Path(remote_item_path).relative_to(base_remote).as_posix()
            if stat.S_ISDIR(item.st_mode):
                structure[rel_path] = {"type": "dir", "size": 0}
                structure.update(get_remote_structure_sftp(sftp, remote_item_path, base_remote))
            else:
                structure[rel_path] = {"type": "file", "size": item.st_size}
    except:
        pass
    return structure

# --- 同步树与计划生成 ---

def generate_sync_plan(local_struct, remote_struct):
    """对比两端结构，生成同步计划"""
    all_paths = sorted(list(set(local_struct.keys()) | set(remote_struct.keys())))
    plan = {"upload": [], "delete": [], "skip": []}
    
    for path in all_paths:
        if path in local_struct and path not in remote_struct:
            plan["upload"].append(path)
        elif path not in local_struct and path in remote_struct:
            plan["delete"].append(path)
        elif path in local_struct and path in remote_struct:
            if local_struct[path]["type"] == "dir":
                plan["skip"].append(path)
            elif local_struct[path]["size"] == remote_struct[path]["size"]:
                plan["skip"].append(path)
            else:
                plan["upload"].append(path)
    return plan

def display_sync_tree(local_struct, remote_struct, project_name):
    """使用 Rich 显示同步预览树"""
    from rich.tree import Tree
    tree = Tree(f"[bold blue]📁 {project_name}[/bold blue] [dim](同步预览)[/dim]")
    nodes = {"": tree}
    all_paths = sorted(list(set(local_struct.keys()) | set(remote_struct.keys())))
    
    for path in all_paths:
        parts = path.split("/")
        parent = "/".join(parts[:-1])
        name = parts[-1]
        
        style, status = "dim", "[未变动]"
        if path in local_struct and path not in remote_struct:
            style, status = "bold green", "[待同步]"
        elif path not in local_struct and path in remote_struct:
            style, status = "bold red", "[待删除]"
        elif local_struct.get(path, {}).get("size") != remote_struct.get(path, {}).get("size") and local_struct.get(path, {}).get("type") == "file":
            style, status = "bold yellow", "[待更新]"
            
        icon = "📁" if (local_struct.get(path) or remote_struct.get(path))["type"] == "dir" else "📄"
        if parent in nodes:
            nodes[path] = nodes[parent].add(f"[{style}]{icon} {name} {status}[/{style}]")
    console.print(tree)

# --- 核心同步执行 ---

def sync_files(project_path: Path, spec: pathspec.PathSpec):
    server_json = project_path / "server.json"
    if not server_json.exists():
        print_error("未找到 server.json")
        return
    
    with open(server_json, "r", encoding="utf-8") as f:
        config_all = json.load(f)
    
    protocol = "ftp" if "ftp" in config_all else "sftp" if "sftp" in config_all else None
    if not protocol:
        print_error("server.json 配置错误")
        return
    
    config = config_all[protocol]
    print_server_info(protocol, config)
    
    # 1. 动画分析
    local_struct, remote_struct = {}, {}
    with console.status("[bold cyan]正在分析同步计划，请稍候...[/bold cyan]", spinner="dots"):
        local_struct = get_local_structure(project_path, project_path, spec)
        try:
            if protocol == "ftp":
                with ftplib.FTP() as ftp:
                    ftp.connect(config["host"], config.get("port", 21), timeout=30)
                    ftp.login(config["user"], config["password"])
                    base = config.get("remote_path") or ftp.pwd()
                    remote_struct = get_remote_structure_ftp(ftp, base, base)
            else:
                import paramiko
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(config["host"], config.get("port", 22), config["user"], config["password"])
                sftp = ssh.open_sftp()
                base = config.get("remote_path") or sftp.normalize(".")
                remote_struct = get_remote_structure_sftp(sftp, base, base)
                sftp.close(); ssh.close()
        except Exception as e:
            print_warning(f"无法获取远程结构: {e}")

    # 2. 生成计划并显示
    plan = generate_sync_plan(local_struct, remote_struct)
    display_sync_tree(local_struct, remote_struct, project_path.name)
    
    if not (plan["upload"] or plan["delete"]):
        print_success("本地与远程已同步，无需操作。")
        return

    if not ask_confirm("确认执行同步计划吗?"):
        return

    # 3. 执行同步
    try:
        if protocol == "ftp":
            run_ftp_plan(project_path, config, plan)
        else:
            run_sftp_plan(project_path, config, plan)
    except Exception as e:
        print_error(f"同步失败: {e}")

def run_ftp_plan(project_root, config, plan):
    with ftplib.FTP() as ftp:
        ftp.connect(config["host"], config.get("port", 21))
        ftp.login(config["user"], config["password"])
        base = config.get("remote_path") or ftp.pwd()
        
        # 上传
        for path in plan["upload"]:
            local_file = project_root / path
            remote_file = (Path(base) / path).as_posix()
            if local_file.is_dir():
                try: ftp.mkd(remote_file)
                except: pass
            else:
                print_info(f"正在上传: {path}")
                # 自动创建父目录
                ensure_remote_dir_ftp(ftp, Path(remote_file).parent.as_posix())
                with open(local_file, "rb") as f:
                    ftp.storbinary(f"STOR {remote_file}", f)
        
        # 删除 (先删文件，后删目录)
        print_step("正在清理远程多余文件...")
        for path in reversed(plan["delete"]):
            remote_item = (Path(base) / path).as_posix()
            try:
                ftp.delete(remote_item)
                print_warning(f"已删除远程文件: {path}")
            except:
                try:
                    ftp.rmd(remote_item)
                    print_warning(f"已删除远程目录: {path}")
                except: pass
    print_success("FTP 同步完成！")

def run_sftp_plan(project_root, config, plan):
    import paramiko
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(config["host"], config.get("port", 22), config["user"], config["password"])
    sftp = ssh.open_sftp()
    base = config.get("remote_path") or sftp.normalize(".")
    
    for path in plan["upload"]:
        local_file = project_root / path
        remote_file = (Path(base) / path).as_posix()
        if local_file.is_dir():
            try: sftp.mkdir(remote_file)
            except: pass
        else:
            print_info(f"正在上传: {path}")
            ensure_remote_dir_sftp(sftp, Path(remote_file).parent.as_posix())
            sftp.put(str(local_file), remote_file)
            
    print_step("正在清理远程多余文件...")
    for path in reversed(plan["delete"]):
        remote_item = (Path(base) / path).as_posix()
        try:
            sftp.remove(remote_item)
            print_warning(f"已删除远程文件: {path}")
        except:
            try:
                sftp.rmdir(remote_item)
                print_warning(f"已删除远程目录: {path}")
            except: pass
    sftp.close(); ssh.close()
    print_success("SFTP 同步完成！")

def ensure_remote_dir_ftp(ftp, path):
    parts = path.strip("/").split("/")
    curr = ""
    for p in parts:
        curr += "/" + p
        try: ftp.mkd(curr)
        except: pass

def ensure_remote_dir_sftp(sftp, path):
    parts = path.strip("/").split("/")
    curr = ""
    for p in parts:
        curr += "/" + p
        try: sftp.mkdir(curr)
        except: pass
