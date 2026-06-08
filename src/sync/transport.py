import concurrent.futures
import ftplib

from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TransferSpeedColumn

from src.config_loader import load_config
from src.filter import is_ignored_path
from src.sync.scanner import normalize_path
from src.ui import console, print_error, print_step, print_warning


def run_sync_action(project_root, config, protocol, plan, source_struct, is_download=False, spec=None):
    """并发执行上传/下载逻辑"""
    failed_files = []
    run_sync_action.last_result = {"failed": 0}

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
                        if is_dir:
                            local_file.mkdir(parents=True, exist_ok=True)
                        else:
                            local_file.parent.mkdir(parents=True, exist_ok=True)
                            with open(local_file, "wb") as f:
                                ftp.retrbinary(f"RETR {remote_file}", f.write)
                    else:
                        if is_dir:
                            try:
                                ftp.mkd(remote_file)
                            except Exception:
                                pass
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
                    if is_dir:
                        local_file.mkdir(parents=True, exist_ok=True)
                    else:
                        local_file.parent.mkdir(parents=True, exist_ok=True)
                        sftp.get(remote_file, str(local_file))
                else:
                    if is_dir:
                        try:
                            sftp.mkdir(remote_file)
                        except Exception:
                            pass
                    else:
                        sftp.put(str(local_file), remote_file)
                sftp.close()
                ssh.close()
            return True, path
        except Exception as e:
            return False, (path, str(e))

    print_step(f"正在准备{'下载' if is_download else '上传'}队列...")
    dirs = [p for p in plan["upload"] if source_struct.get(p, {}).get("type") == "dir"]
    files = [p for p in plan["upload"] if source_struct.get(p, {}).get("type") != "dir"]

    if dirs:
        for d in dirs:
            success, res = process_file(d)
            if not success:
                failed_files.append(res)

    if files:
        config_data = load_config()
        max_workers = config_data.get("max_workers", 3)

        action_name = "下载" if is_download else "上传"
        print_step(f"正在并发{action_name}文件 ({len(files)} 个, 并发数: {max_workers})...")
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TransferSpeedColumn(),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task(f"{action_name}中...", total=len(files))
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_path = {executor.submit(process_file, p): p for p in files}
                for future in concurrent.futures.as_completed(future_to_path):
                    success, result = future.result()
                    if not success:
                        failed_files.append(result)
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
                                except Exception:
                                    try:
                                        ftp.rmd(item)
                                    except Exception:
                                        pass
                        except Exception as e:
                            failed_files.append((path, str(e)))
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
                            except Exception:
                                try:
                                    sftp.rmdir(item)
                                except Exception:
                                    pass
                    except Exception as e:
                        failed_files.append((path, str(e)))
                sftp.close()
                ssh.close()
        except Exception as e:
            print_error(f"清理阶段失败: {e}")

    if failed_files:
        run_sync_action.last_result = {"failed": len(failed_files)}
        print_warning(f"\n⚠️ 操作完成，但有 {len(failed_files)} 个项处理失败。")
        for path, error in failed_files[:5]:
            print_warning(f"失败项: {path} -> {error}")
        if len(failed_files) > 5:
            print_warning(f"其余 {len(failed_files) - 5} 个失败项已省略。")
        return False
    run_sync_action.last_result = {"failed": 0}
    return True
