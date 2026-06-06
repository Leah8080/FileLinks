import ftplib
import json
import stat
import concurrent.futures
import shutil
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TransferSpeedColumn
from src.ui import print_step, print_error, print_warning, console
from src.sync.scanner import SYNC_STATE_FILENAME, normalize_path
from src.config_loader import load_config

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
