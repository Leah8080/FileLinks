import ftplib
import json

from src.sync.scanner import SYNC_STATE_FILENAME, normalize_path
from src.ui import print_step, print_warning


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
                except Exception:
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
            except Exception:
                return None
            finally:
                sftp.close()
                ssh.close()
    except Exception:
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
            sftp.close()
            ssh.close()
    except Exception as e:
        print_warning(f"无法同步状态到云端: {e}")
