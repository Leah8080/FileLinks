import ftplib
import json
import stat
import concurrent.futures
import time
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TransferSpeedColumn
from src.ui import print_step, print_info, print_error, print_warning, console
from src.sync.scanner import SYNC_STATE_FILENAME, normalize_path
from src.config_loader import load_config
from src.filter import get_ignore_match_source, is_ignored_path

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
    print_step("正在更新云端同步状态...")
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

def wipe_remote(protocol, config, spec=None):
    """完全清空远程目录"""
    def ftp_remove_dir(ftp, path, base):
        for name, facts in ftp.mlsd(path):
            if name in (".", ".."): continue
            full_path = f"{path}/{name}"
            rel_path = normalize_path(full_path)[len(base):].lstrip("/")
            is_dir = facts['type'] == 'dir'
            if spec and is_ignored_path(rel_path, spec, is_dir):
                continue
            if is_dir:
                ftp_remove_dir(ftp, full_path, base)
            else:
                ftp.delete(full_path)
        try:
            ftp.rmd(path)
        except:
            pass

    def sftp_remove_dir(sftp, path, base):
        for item in sftp.listdir_attr(path):
            if item.filename in (".", ".."): continue
            full_path = f"{path}/{item.filename}"
            rel_path = normalize_path(full_path)[len(base):].lstrip("/")
            is_dir = stat.S_ISDIR(item.st_mode)
            if spec and is_ignored_path(rel_path, spec, is_dir):
                continue
            if is_dir:
                sftp_remove_dir(sftp, full_path, base)
            else:
                sftp.remove(full_path)
        try:
            sftp.rmdir(path)
        except:
            pass

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
                    rel_path = normalize_path(full_path)[len(base):].lstrip("/")
                    is_dir = facts['type'] == 'dir'
                    if spec and is_ignored_path(rel_path, spec, is_dir):
                        continue
                    if is_dir:
                        ftp_remove_dir(ftp, full_path, base)
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
                rel_path = normalize_path(full_path)[len(base):].lstrip("/")
                is_dir = stat.S_ISDIR(item.st_mode)
                if spec and is_ignored_path(rel_path, spec, is_dir):
                    continue
                if is_dir:
                    sftp_remove_dir(sftp, full_path, base)
                else:
                    sftp.remove(full_path)
            sftp.close(); ssh.close()
        return True
    except Exception as e:
        print_error(f"清空远程目录失败: {e}")
        return False

def run_sync_action(project_root, config, protocol, plan, source_struct, is_download=False, spec=None):
    """并发执行上传/下载逻辑"""
    failed_files = []

    def remove_local_item(item, rel_path):
        is_dir = item.is_dir()
        if spec and is_ignored_path(rel_path, spec, is_dir):
            return
        if item.is_file():
            item.unlink()
            return
        if item.is_dir():
            for child in item.iterdir():
                child_rel = child.relative_to(project_root).as_posix().strip("/")
                remove_local_item(child, child_rel)
            try:
                item.rmdir()
            except OSError:
                pass
    
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
                                remove_local_item(item, path)
                            else:
                                item = normalize_path(f"{base}/{path}")
                                try:
                                    ftp.delete(item)
                                except:
                                    try: ftp.rmd(item)
                                    except: pass
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
                            remove_local_item(item, path)
                        else:
                            item = normalize_path(f"{base}/{path}")
                            try:
                                sftp.remove(item)
                            except:
                                try: sftp.rmdir(item)
                                except: pass
                    except Exception as e: failed_files.append((path, str(e)))
                sftp.close(); ssh.close()
        except Exception as e:
            print_error(f"清理阶段失败: {e}")

    if failed_files:
        print_warning(f"\n⚠️ 操作完成，但有 {len(failed_files)} 个项处理失败。")
        for path, error in failed_files[:5]:
            print_warning(f"失败项: {path} -> {error}")
        if len(failed_files) > 5:
            print_warning(f"其余 {len(failed_files) - 5} 个失败项已省略。")
        return False
    return True

def get_real_remote_structure(protocol, config, spec=None, ignored_paths=None):
    started_at = time.perf_counter()
    scan_stats = {"dirs": 0, "files": 0, "filtered": 0}
    try:
        if protocol == "ftp":
            with ftplib.FTP() as ftp:
                ftp.set_pasv(True)
                ftp.connect(config["host"], config.get("port", 21), timeout=30)
                ftp.login(config["user"], config["password"])
                remote_path = config.get("remote_path")
                pwd = ftp.pwd()
                base = normalize_path(remote_path if remote_path and remote_path != "/" else pwd)
                print_info(f"正在读取 FTP 远程结构, 根目录: {base}")
                struct = get_remote_structure_ftp(ftp, base, base, spec, ignored_paths, scan_stats)
                _print_remote_scan_stats(scan_stats, started_at)
                return struct
        else:
            import paramiko
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(config["host"], config.get("port", 22), config["user"], config["password"])
            sftp = ssh.open_sftp()
            remote_path = config.get("remote_path")
            
            # 确定基础路径
            try:
                # 尝试获取当前目录的标准化路径（在翼龙面板通常是 /）
                try:
                    home = normalize_path(sftp.normalize("."))
                except:
                    home = "/"

                if not remote_path or remote_path == "/":
                    base = home
                else:
                    base = normalize_path(remote_path)
                
                # 验证路径是否存在
                try:
                    sftp.stat(base)
                except:
                    # 如果指定的路径失败，且看起来像是绝对路径，尝试回退到 /
                    if base != "/" and base != home:
                        print_warning(f"无法访问路径 {base}，检测到可能是翼龙面板等受限环境。")
                        print_info("提示：请在‘主机配置’中将远程路径设为 / 或留空。")
                        print_step("尝试以根目录 '/' 重新读取...")
                        base = "/"
                        try:
                            sftp.stat(base)
                        except:
                            print_error("仍无法访问远程根目录。")
                            return {}
                
                print_info(f"正在读取 SFTP 远程结构, 根目录: {base}")
                struct = get_remote_structure_sftp(sftp, base, base, spec, ignored_paths, scan_stats)
            finally:
                sftp.close(); ssh.close()
            _print_remote_scan_stats(scan_stats, started_at)
            return struct
    except Exception as e:
        print_error(f"连接或读取远程结构失败: {e}")
        return {}

def _print_remote_scan_stats(stats, started_at):
    elapsed = time.perf_counter() - started_at
    print_info(
        f"远程扫描完成：目录 {stats['dirs']}，文件 {stats['files']}，"
        f"已过滤 {stats['filtered']}，耗时 {elapsed:.2f}s"
    )

def get_remote_structure_ftp(ftp, current_remote, base_remote, spec=None, ignored_paths=None, scan_stats=None):
    structure = {}
    try:
        for name, facts in ftp.mlsd(current_remote):
            if name in (".", ".."): continue
            rel_path = normalize_path(f"{current_remote}/{name}")[len(base_remote):].lstrip("/")
            is_dir = facts['type'] == 'dir'
            if name == SYNC_STATE_FILENAME or (spec and is_ignored_path(rel_path, spec, is_dir)):
                if scan_stats is not None:
                    scan_stats["filtered"] += 1
                if ignored_paths is not None:
                    ignored_paths[rel_path] = {
                        "type": "dir" if is_dir else "file",
                        "size": 0 if is_dir else int(facts.get('size', 0)),
                        "ignored_by": get_ignore_match_source(rel_path, spec, is_dir),
                        "origin": "remote"
                    }
                continue
            if is_dir:
                if scan_stats is not None:
                    scan_stats["dirs"] += 1
                structure[rel_path] = {"type": "dir", "size": 0}
                structure.update(get_remote_structure_ftp(ftp, f"{current_remote}/{name}", base_remote, spec, ignored_paths, scan_stats))
            else:
                if scan_stats is not None:
                    scan_stats["files"] += 1
                structure[rel_path] = {"type": "file", "size": int(facts.get('size', 0))}
    except Exception as e:
        print_warning(f"无法读取远程目录 {current_remote}: {e}")
    return structure

def get_remote_structure_sftp(sftp, current_remote, base_remote, spec=None, ignored_paths=None, scan_stats=None):
    structure = {}
    try:
        # 尝试列出目录内容
        items = sftp.listdir_attr(current_remote)
        for item in items:
            if item.filename in (".", ".."): continue
            
            # 构造路径时避免双斜杠
            full_path = current_remote.rstrip("/") + "/" + item.filename
            rel_path = normalize_path(full_path)[len(base_remote):].lstrip("/")
            is_dir = stat.S_ISDIR(item.st_mode)
            if item.filename == SYNC_STATE_FILENAME or (spec and is_ignored_path(rel_path, spec, is_dir)):
                if scan_stats is not None:
                    scan_stats["filtered"] += 1
                if ignored_paths is not None:
                    ignored_paths[rel_path] = {
                        "type": "dir" if is_dir else "file",
                        "size": 0 if is_dir else item.st_size,
                        "ignored_by": get_ignore_match_source(rel_path, spec, is_dir),
                        "origin": "remote"
                    }
                continue
            
            if is_dir:
                if scan_stats is not None:
                    scan_stats["dirs"] += 1
                structure[rel_path] = {"type": "dir", "size": 0}
                structure.update(get_remote_structure_sftp(sftp, full_path, base_remote, spec, ignored_paths, scan_stats))
            else:
                if scan_stats is not None:
                    scan_stats["files"] += 1
                structure[rel_path] = {"type": "file", "size": item.st_size}
    except Exception as e:
        print_warning(f"无法读取远程目录 {current_remote}: {e}")
    return structure
