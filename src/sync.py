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

SYNC_STATE_FILENAME = ".sync_state"

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

def generate_sync_plan(source_struct, target_struct, cache_struct=None):
    """对比两端结构，生成同步计划"""
    if cache_struct is None: cache_struct = {}
    
    all_paths = sorted(list(set(source_struct.keys()) | set(target_struct.keys())))
    plan = {"upload": [], "delete": [], "skip": []}
    stats = {"added": 0, "updated": 0, "deleted": 0}
    path_states = {}
    
    for path in all_paths:
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
                        # 如果目标没有 MD5 (比如直接扫描的远程结构)，对比缓存
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
    console.print(Panel(summary, title="📊 同步摘要", expand=False))
    
    tree = Tree(f"[bold blue]📁 {project_name}[/bold blue]")
    nodes = {"": tree}
    all_paths = sorted(path_states.keys())
    
    for path in all_paths:
        parts = path.split("/")
        parent = "/".join(parts[:-1])
        name = parts[-1]
        
        state = path_states[path]
        if state == "none" and not any(p.startswith(path + "/") for p in path_states if path_states[p] != "none"):
            continue # 隐藏没有变化的目录（除非其子目录有变化）

        style, label = "dim", ""
        if state == "added":
            style, label = "bold green", f"[待{action_text}]"
        elif state == "deleted":
            style, label = "bold red", "[待删除]"
        elif state == "updated":
            style, label = "bold yellow", "[待更新]"
            
        icon = "📁" if (source_struct.get(path) or target_struct.get(path))["type"] == "dir" else "📄"
        display_text = f"[{style}]{icon} {name} {label}[/{style}]"
        
        if parent in nodes:
            nodes[path] = nodes[parent].add(display_text)
            
    console.print(tree)

# --- 工作流 ---

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
    
    local_struct = get_local_structure(project_path, project_path, spec)
    local_state = load_sync_state(project_path)
    remote_state = fetch_remote_state(protocol, config)

    # 情况 1: 首次同步 (本地没有状态)
    if not local_state:
        print_warning("检测到首次同步（本地无记录）。")
        if ask_confirm("是否清空远程目录并完整上传本地项目？"):
            if wipe_remote(protocol, config):
                plan = {"upload": sorted(local_struct.keys()), "delete": [], "skip": []}
                # 执行上传...
                if run_sync_action(project_path, config, protocol, plan, local_struct, is_download=False):
                    save_sync_state(project_path, local_struct)
                    push_remote_state(protocol, config, local_struct)
                    print_success("首次同步完成！")
                    return True
            return False
        else:
            print_info("已取消。如果你想保留远程文件，请先执行“同步云端”以初始化状态。")
            return False

    # 情况 2: 增量同步
    if remote_state and remote_state != local_state:
        print_warning("⚠️ 注意：远程状态与本地记录不符，远程文件可能已被他人修改。")
        if not ask_confirm("仍要以本地为准进行覆盖同步吗？"):
            return False

    # 使用本地当前结构作为源，远程状态（或本地状态）作为目标
    target_for_plan = remote_state if remote_state else local_state
    plan, path_states, stats = generate_sync_plan(local_struct, target_for_plan, local_state)
    
    if not (plan["upload"] or plan["delete"]):
        print_success("本地与远程已同步。")
        # 即使没操作，也确保远程有状态文件
        if not remote_state: push_remote_state(protocol, config, local_struct)
        return True

    display_sync_tree(path_states, local_struct, target_for_plan, project_path.name, stats)
    if ask_confirm("确认执行同步计划？"):
        if run_sync_action(project_path, config, protocol, plan, local_struct, is_download=False):
            save_sync_state(project_path, local_struct)
            push_remote_state(protocol, config, local_struct)
            print_success("同步成功！")
            return True
    return False

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
    
    local_state = load_sync_state(project_path)
    remote_state = fetch_remote_state(protocol, config)
    
    # 获取真正的远程结构 (如果远程没有状态文件)
    if not remote_state:
        print_info("远程没有状态文件，正在扫描远程结构...")
        with console.status("[cyan]扫描中..."):
            remote_state = get_real_remote_structure(protocol, config)

    # 情况 1: 本地没有状态 (首次下载)
    if not local_state:
        print_warning("检测到本地无同步记录。")
        if not ask_confirm("是否从云端完整下载项目到本地？"):
            return False
        local_struct = {}
    else:
        local_struct = get_local_structure(project_path, project_path, spec)

    # 计划：源=远程状态，目标=本地当前
    plan, path_states, stats = generate_sync_plan(remote_state, local_struct, local_state)
    
    if not (plan["upload"] or plan["delete"]):
        print_success("本地已是最新。")
        save_sync_state(project_path, remote_state) # 确保本地有状态
        return True

    display_sync_tree(path_states, remote_state, local_struct, project_path.name, stats, is_download=True)
    if ask_confirm("确认从云端同步到本地？(本地多余文件将被删除)"):
        if run_sync_action(project_path, config, protocol, plan, remote_state, is_download=True):
            # 重新扫描本地以确保状态准确
            new_local = get_local_structure(project_path, project_path, spec)
            save_sync_state(project_path, new_local)
            push_remote_state(protocol, config, new_local)
            print_success("云端同步完成！")
            return True
    return False

# --- 执行底座 ---

def run_sync_action(project_root, config, protocol, plan, source_struct, is_download=False):
    """统一的执行逻辑"""
    failed_files = []
    
    try:
        if protocol == "ftp":
            with ftplib.FTP() as ftp:
                ftp.set_pasv(True)
                ftp.connect(config["host"], config.get("port", 21), timeout=60)
                ftp.login(config["user"], config["password"])
                base = normalize_path(config.get("remote_path") or ftp.pwd())
                
                if plan["upload"]:
                    print_step(f"正在{'下载' if is_download else '上传'}文件...")
                    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), BarColumn(), TaskProgressColumn(), TransferSpeedColumn(), console=console) as progress:
                        for path in plan["upload"]:
                            local_file = project_root / path
                            remote_file = normalize_path(f"{base}/{path}")
                            is_dir = source_struct.get(path, {}).get("type") == "dir"
                            
                            try:
                                if is_download:
                                    if is_dir: local_file.mkdir(parents=True, exist_ok=True)
                                    else:
                                        local_file.parent.mkdir(parents=True, exist_ok=True)
                                        size = source_struct.get(path, {}).get("size", 0)
                                        task = progress.add_task(f"下载 {path}", total=size)
                                        with open(local_file, "wb") as f:
                                            ftp.retrbinary(f"RETR {remote_file}", callback=lambda d: (f.write(d), progress.update(task, advance=len(d))))
                                        progress.remove_task(task)
                                else: # 上传
                                    if is_dir: 
                                        try: ftp.mkd(remote_file)
                                        except: pass
                                    else:
                                        ensure_remote_dir_ftp(ftp, os.path.dirname(remote_file))
                                        size = local_file.stat().st_size
                                        task = progress.add_task(f"上传 {path}", total=size)
                                        with open(local_file, "rb") as f:
                                            ftp.storbinary(f"STOR {remote_file}", f, callback=lambda d: progress.update(task, advance=len(d)))
                                        progress.remove_task(task)
                            except Exception as e:
                                failed_files.append((path, str(e)))

                if plan["delete"]:
                    print_step(f"正在清理{'本地' if is_download else '远程'}多余文件...")
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
                        except Exception as e:
                            failed_files.append((path, str(e)))
        else:
            import paramiko
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(config["host"], config.get("port", 22), config["user"], config["password"])
            sftp = ssh.open_sftp()
            base = normalize_path(config.get("remote_path") or sftp.normalize("."))
            
            if plan["upload"]:
                print_step(f"正在{'下载' if is_download else '上传'}文件...")
                with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), BarColumn(), TaskProgressColumn(), TransferSpeedColumn(), console=console) as progress:
                    for path in plan["upload"]:
                        local_file = project_root / path
                        remote_file = normalize_path(f"{base}/{path}")
                        is_dir = source_struct.get(path, {}).get("type") == "dir"
                        
                        try:
                            if is_download:
                                if is_dir: local_file.mkdir(parents=True, exist_ok=True)
                                else:
                                    local_file.parent.mkdir(parents=True, exist_ok=True)
                                    size = source_struct.get(path, {}).get("size", 0)
                                    task = progress.add_task(f"下载 {path}", total=size)
                                    sftp.get(remote_file, str(local_file), callback=lambda c, t: progress.update(task, completed=c))
                                    progress.remove_task(task)
                            else: # 上传
                                if is_dir:
                                    try: sftp.mkdir(remote_file)
                                    except: pass
                                else:
                                    ensure_remote_dir_sftp(sftp, os.path.dirname(remote_file))
                                    size = local_file.stat().st_size
                                    task = progress.add_task(f"上传 {path}", total=size)
                                    sftp.put(str(local_file), remote_file, callback=lambda c, t: progress.update(task, completed=c))
                                    progress.remove_task(task)
                        except Exception as e:
                            failed_files.append((path, str(e)))

            if plan["delete"]:
                print_step(f"正在清理{'本地' if is_download else '远程'}多余文件...")
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
                    except Exception as e:
                        failed_files.append((path, str(e)))
            sftp.close(); ssh.close()

        if failed_files:
            print_warning("\n⚠️ 操作完成，但部分文件失败：")
            for p, e in failed_files[:10]: print_error(f"  - {p}: {e}")
            return False
        return True
    except Exception as e:
        print_error(f"执行失败: {e}")
        return False

# --- 辅助工具 ---

def get_real_remote_structure(protocol, config):
    """手动扫描远程结构 (没有状态文件时)"""
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
    if path == "/": return
    parts = path.strip("/").split("/")
    curr = ""
    for p in parts:
        curr += "/" + p
        try: ftp.mkd(curr)
        except: pass

def ensure_remote_dir_sftp(sftp, path):
    if path == "/": return
    parts = path.strip("/").split("/")
    curr = ""
    for p in parts:
        curr += "/" + p
        try: sftp.mkdir(curr)
        except: pass
