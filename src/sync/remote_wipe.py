import ftplib
import stat

from src.filter import is_ignored_path
from src.sync.scanner import normalize_path
from src.ui import print_error, print_step


def wipe_remote(protocol, config, spec=None):
    """完全清空远程目录"""

    def ftp_remove_dir(ftp, path, base):
        for name, facts in ftp.mlsd(path):
            if name in (".", ".."):
                continue
            full_path = f"{path}/{name}"
            rel_path = normalize_path(full_path)[len(base):].lstrip("/")
            is_dir = facts["type"] == "dir"
            if spec and is_ignored_path(rel_path, spec, is_dir):
                continue
            if is_dir:
                ftp_remove_dir(ftp, full_path, base)
            else:
                ftp.delete(full_path)
        try:
            ftp.rmd(path)
        except Exception:
            pass

    def sftp_remove_dir(sftp, path, base):
        for item in sftp.listdir_attr(path):
            if item.filename in (".", ".."):
                continue
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
        except Exception:
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
                    if name in (".", ".."):
                        continue
                    full_path = f"{base}/{name}"
                    rel_path = normalize_path(full_path)[len(base):].lstrip("/")
                    is_dir = facts["type"] == "dir"
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
                if item.filename in (".", ".."):
                    continue
                full_path = f"{base}/{item.filename}"
                rel_path = normalize_path(full_path)[len(base):].lstrip("/")
                is_dir = stat.S_ISDIR(item.st_mode)
                if spec and is_ignored_path(rel_path, spec, is_dir):
                    continue
                if is_dir:
                    sftp_remove_dir(sftp, full_path, base)
                else:
                    sftp.remove(full_path)
            sftp.close()
            ssh.close()
        return True
    except Exception as e:
        print_error(f"清空远程目录失败: {e}")
        return False
