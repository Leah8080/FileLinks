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
from src.ui import print_info, print_success, print_error, print_warning, print_step, print_server_info, ask_confirm, console
from src.filter import is_ignored

import hashlib

# --- 辅助函数 ---

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
    state_file = project_path / ".sync_state.json"
    if state_file.exists():
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_sync_state(project_path: Path, state: dict):
    """保存当前同步状态到缓存"""
    state_file = project_path / ".sync_state.json"
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

def generate_sync_plan(local_struct, remote_struct, cache_struct=None):
    """对比两端结构，生成同步计划"""
    if cache_struct is None:
        cache_struct = {}
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
            else:
                # 文件对比：
                # 1. 优先对比文件大小是否变化
                # 2. 如果大小一致，检查缓存：若 MD5 改变，说明是同大小修改；若没有缓存，则认为无变化
                is_modified = False
                if local_struct[path]["size"] != remote_struct[path]["size"]:
                    is_modified = True
                elif path in cache_struct:
                    local_md5 = local_struct[path].get("md5", "")
                    cached_md5 = cache_struct[path].get("md5", "")
                    if local_md5 and cached_md5 and local_md5 != cached_md5:
                        is_modified = True
                
                if is_modified:
                    plan["upload"].append(path)
                    path_states[path] = "updated"
                    stats["updated"] += 1
                else:
                    plan["skip"].append(path)
                    path_states[path] = "none"
                
    return plan, path_states, stats

def display_sync_tree(path_states, local_struct, remote_struct, project_name, stats, is_download=False):
    """显示优化的同步预览树"""
    from rich.tree import Tree
    action_text = "下载" if is_download else "同步"
    summary = f"[bold green]+ {stats['added']} 待{action_text}[/bold green]  " \
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
            style, label = "bold green", f"[待{action_text}]"
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

def sync_to_remote(project_path: Path, spec: pathspec.PathSpec):
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

    cache_struct = load_sync_state(project_path)
    plan, path_states, stats = generate_sync_plan(local_struct, remote_struct, cache_struct)
    display_sync_tree(path_states, local_struct, remote_struct, project_path.name, stats)
    
    if not (plan["upload"] or plan["delete"]):
        save_sync_state(project_path, local_struct)
        print_success("本地与远程完全一致，无需操作。")
        return False

    if not ask_confirm("确认执行上述同步计划吗?"):
        print_warning("已取消同步操作。")
        return False

    try:
        if protocol == "ftp":
            failed_files = run_ftp_plan(project_path, config, plan)
        else:
            failed_files = run_sftp_plan(project_path, config, plan)
        
        # 即使部分文件失败，也要更新成功上传的文件的状态缓存
        success_struct = local_struct.copy()
        for failed_path, _ in failed_files:
            if failed_path in success_struct:
                if failed_path in cache_struct:
                    success_struct[failed_path] = cache_struct[failed_path]
                else:
                    del success_struct[failed_path]
        
        save_sync_state(project_path, success_struct)
        
        # 最终汇总报告
        if failed_files:
            print_warning("\n⚠️ 同步完成，但以下文件处理失败：")
            for path, err in failed_files:
                print_error(f"  - {path} : {err}")
            return False
        else:
            print_success("\n🎉 所有文件同步成功！")
            return True
    except Exception as e:
        print_error(f"同步失败: {e}")
        return False

def run_ftp_plan(project_root, config, plan):
    failed_files = []
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
                        except Exception as e:
                            print_error(f"创建远程目录失败 {path}: {e}")
                            failed_files.append((path, f"创建目录失败: {e}"))
                    else:
                        task = progress.add_task(f"上传 {path}", total=local_file.stat().st_size)
                        ensure_remote_dir_ftp(ftp, normalize_path(os.path.dirname(remote_file)))
                        try:
                            with open(local_file, "rb") as f:
                                ftp.storbinary(f"STOR {remote_file}", f, callback=lambda chunk: progress.update(task, advance=len(chunk)))
                        except ftplib.error_perm as e:
                            err_msg = str(e)
                            if "553" in err_msg or "550" in err_msg:
                                try:
                                    ftp.delete(remote_file)
                                    with open(local_file, "rb") as f:
                                        ftp.storbinary(f"STOR {remote_file}", f, callback=lambda chunk: progress.update(task, advance=len(chunk)))
                                except Exception as retry_err:
                                    progress.remove_task(task)
                                    print_error(f"上传失败 {path}: 权限错误，重试失败: {retry_err}")
                                    failed_files.append((path, f"权限错误，重试失败: {retry_err}"))
                                else:
                                    progress.remove_task(task)
                            else:
                                progress.remove_task(task)
                                print_error(f"上传失败 {path}: {e}")
                                failed_files.append((path, str(e)))
                        except Exception as e:
                            progress.remove_task(task)
                            print_error(f"上传失败 {path}: {e}")
                            failed_files.append((path, str(e)))
                        else:
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
                        except Exception as e2:
                            print_error(f"删除失败 {path}: {e2}")
                            failed_files.append((path, f"删除失败: {e2}"))
        except Exception as e:
            print_error(f"清理阶段连接失败: {e}")
            for path in reversed(plan["delete"]):
                failed_files.append((path, f"清理阶段连接失败: {e}"))
    return failed_files

def run_sftp_plan(project_root, config, plan):
    failed_files = []
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
                    except Exception as e:
                        print_error(f"创建远程目录失败 {path}: {e}")
                        failed_files.append((path, f"创建目录失败: {e}"))
                else:
                    task = progress.add_task(f"上传 {path}", total=local_file.stat().st_size)
                    ensure_remote_dir_sftp(sftp, normalize_path(os.path.dirname(remote_file)))
                    try:
                        sftp.put(str(local_file), remote_file, callback=lambda cur, tot: progress.update(task, completed=cur))
                    except Exception as e:
                        print_error(f"上传失败 {path}: {e}")
                        failed_files.append((path, str(e)))
                    finally:
                        progress.remove_task(task)
            
    if plan["delete"]:
        print_step("正在清理远程多余文件...")
        for path in reversed(plan["delete"]):
            remote_item = normalize_path(f"{base}/{path}")
            try:
                sftp.remove(remote_item)
                print_warning(f"已删除: {path}")
            except Exception as e:
                try:
                    sftp.rmdir(remote_item)
                    print_warning(f"已删除目录: {path}")
                except Exception as e2:
                    print_error(f"删除失败 {path}: {e2}")
                    failed_files.append((path, f"删除失败: {e2}"))
                
    sftp.close(); ssh.close()
    return failed_files

def sync_from_remote(project_path: Path, spec: pathspec.PathSpec):
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
            print_error(f"连接远程服务器失败: {e}")
            return False

    # 注意：下载同步时，我们将 remote_struct 作为“源”，local_struct 作为“目标”
    # 这样 plan["upload"] 就是需要下载的文件，plan["delete"] 就是本地多余需要删除的文件
    cache_struct = load_sync_state(project_path)
    plan, path_states, stats = generate_sync_plan(remote_struct, local_struct, cache_struct)
    display_sync_tree(path_states, remote_struct, local_struct, project_path.name, stats, is_download=True)
    
    if not (plan["upload"] or plan["delete"]):
        print_success("本地与远程完全一致，无需下载。")
        return False

    if not ask_confirm("确认从云端同步到本地吗? (本地多余文件将被删除)"):
        print_warning("已取消同步操作。")
        return False

    try:
        if protocol == "ftp":
            failed_files = run_ftp_download_plan(project_path, config, plan)
        else:
            failed_files = run_sftp_download_plan(project_path, config, plan)
        
        # 更新同步状态缓存 (以本地最新结构为准)
        new_local_struct = get_local_structure(project_path, project_path, spec)
        save_sync_state(project_path, new_local_struct)
        
        if failed_files:
            print_warning("\n⚠️ 下载完成，但以下文件处理失败：")
            for path, err in failed_files:
                print_error(f"  - {path} : {err}")
            return False
        else:
            print_success("\n🎉 所有文件下载成功！")
            return True
    except Exception as e:
        print_error(f"下载失败: {e}")
        return False

def run_ftp_download_plan(project_root, config, plan):
    failed_files = []
    with ftplib.FTP() as ftp:
        ftp.set_pasv(True)
        ftp.connect(config["host"], config.get("port", 21), timeout=60)
        ftp.login(config["user"], config["password"])
        base = normalize_path(config.get("remote_path") or ftp.pwd())
        
        if plan["upload"]: # 这里的 upload 实际上是下载
            print_step("正在下载文件...")
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
                    
                    # 检查远程是否是目录（在 FTP 中判断稍复杂，这里假设 path_states 中已包含信息）
                    # 实际上 generate_sync_plan 已经根据 remote_struct 判定了类型
                    if not remote_file.endswith("/") and "." not in os.path.basename(remote_file) and "/" not in path:
                         # 简单的启发式判断，可能不准确，更好的是看 remote_struct
                         pass

                    # 实际上我们可以从计划中获取类型信息，或者简单地尝试下载
                    try:
                        # 确保本地目录存在
                        local_file.parent.mkdir(parents=True, exist_ok=True)
                        
                        # 尝试获取大小用于进度条
                        try: size = ftp.size(remote_file)
                        except: size = 0
                        
                        if size is None: # 说明是目录
                            local_file.mkdir(parents=True, exist_ok=True)
                            continue

                        task = progress.add_task(f"下载 {path}", total=size)
                        with open(local_file, "wb") as f:
                            ftp.retrbinary(f"RETR {remote_file}", callback=lambda chunk: progress.update(task, advance=len(chunk)))
                        progress.remove_task(task)
                    except Exception as e:
                        print_error(f"下载失败 {path}: {e}")
                        failed_files.append((path, str(e)))
        
    if plan["delete"]:
        print_step("正在清理本地多余文件...")
        for path in reversed(plan["delete"]):
            local_item = project_root / path
            try:
                if local_item.is_file():
                    local_item.unlink()
                    print_warning(f"已删除本地文件: {path}")
                elif local_item.is_dir():
                    import shutil
                    shutil.rmtree(local_item)
                    print_warning(f"已删除本地目录: {path}")
            except Exception as e:
                print_error(f"本地删除失败 {path}: {e}")
                failed_files.append((path, f"本地删除失败: {e}"))
    return failed_files

def run_sftp_download_plan(project_root, config, plan):
    failed_files = []
    import paramiko
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(config["host"], config.get("port", 22), config["user"], config["password"])
    sftp = ssh.open_sftp()
    base = normalize_path(config.get("remote_path") or sftp.normalize("."))
    
    if plan["upload"]: # 这里的 upload 实际上是下载
        print_step("正在下载文件...")
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
                
                try:
                    # 确保本地目录存在
                    local_file.parent.mkdir(parents=True, exist_ok=True)
                    
                    # 获取远程属性
                    attr = sftp.stat(remote_file)
                    if stat.S_ISDIR(attr.st_mode):
                        local_file.mkdir(parents=True, exist_ok=True)
                        continue
                    
                    task = progress.add_task(f"下载 {path}", total=attr.st_size)
                    sftp.get(remote_file, str(local_file), callback=lambda cur, tot: progress.update(task, completed=cur))
                    progress.remove_task(task)
                except Exception as e:
                    print_error(f"下载失败 {path}: {e}")
                    failed_files.append((path, str(e)))
            
    if plan["delete"]:
        print_step("正在清理本地多余文件...")
        for path in reversed(plan["delete"]):
            local_item = project_root / path
            try:
                if local_item.is_file():
                    local_item.unlink()
                    print_warning(f"已删除本地文件: {path}")
                elif local_item.is_dir():
                    import shutil
                    shutil.rmtree(local_item)
                    print_warning(f"已删除本地目录: {path}")
            except Exception as e:
                print_error(f"本地删除失败 {path}: {e}")
                failed_files.append((path, f"本地删除失败: {e}"))
                
    sftp.close(); ssh.close()
    return failed_files

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
