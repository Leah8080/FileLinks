import ftplib
import stat
import time

from src.filter import get_ignore_match_source, is_ignored_path
from src.sync.scanner import SYNC_STATE_FILENAME, normalize_path
from src.ui import print_error, print_info, print_step, print_warning


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

            try:
                try:
                    home = normalize_path(sftp.normalize("."))
                except Exception:
                    home = "/"

                if not remote_path or remote_path == "/":
                    base = home
                else:
                    base = normalize_path(remote_path)

                try:
                    sftp.stat(base)
                except Exception:
                    if base != "/" and base != home:
                        print_warning(f"无法访问路径 {base}，检测到可能是翼龙面板等受限环境。")
                        print_info("提示：请在‘主机配置’中将远程路径设为 / 或留空。")
                        print_step("尝试以根目录 '/' 重新读取...")
                        base = "/"
                        try:
                            sftp.stat(base)
                        except Exception:
                            print_error("仍无法访问远程根目录。")
                            return {}

                print_info(f"正在读取 SFTP 远程结构, 根目录: {base}")
                struct = get_remote_structure_sftp(sftp, base, base, spec, ignored_paths, scan_stats)
            finally:
                sftp.close()
                ssh.close()
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
            if name in (".", ".."):
                continue
            rel_path = normalize_path(f"{current_remote}/{name}")[len(base_remote):].lstrip("/")
            is_dir = facts["type"] == "dir"
            if name == SYNC_STATE_FILENAME or (spec and is_ignored_path(rel_path, spec, is_dir)):
                if scan_stats is not None:
                    scan_stats["filtered"] += 1
                if ignored_paths is not None:
                    ignored_paths[rel_path] = {
                        "type": "dir" if is_dir else "file",
                        "size": 0 if is_dir else int(facts.get("size", 0)),
                        "ignored_by": get_ignore_match_source(rel_path, spec, is_dir),
                        "origin": "remote",
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
                structure[rel_path] = {"type": "file", "size": int(facts.get("size", 0))}
    except Exception as e:
        print_warning(f"无法读取远程目录 {current_remote}: {e}")
    return structure


def get_remote_structure_sftp(sftp, current_remote, base_remote, spec=None, ignored_paths=None, scan_stats=None):
    structure = {}
    try:
        items = sftp.listdir_attr(current_remote)
        for item in items:
            if item.filename in (".", ".."):
                continue

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
                        "origin": "remote",
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
