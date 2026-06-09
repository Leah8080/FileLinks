import json
from pathlib import Path

from src.sync.scanner import normalize_path
from src.ui import ask_input, print_error, print_info, print_step, print_success


def get_server_config(project_path):
    server_json = project_path / "server.json"
    if not server_json.exists():
        return None
    try:
        with open(server_json, "r", encoding="utf-8") as f:
            config_all = json.load(f)
        protocol = "ftp" if "ftp" in config_all else "sftp" if "sftp" in config_all else None
        if not protocol:
            return None
        return protocol, config_all[protocol]
    except Exception:
        return None


def manage_host_config(project_path: Path):
    """交互式管理主机配置"""
    print_step("配置远程主机信息")
    current = get_server_config(project_path)

    def_proto = "sftp"
    def_host, def_port, def_user, def_pass, def_path = "", "", "", "", "/"

    if current:
        def_proto, cfg = current
        def_host = cfg.get("host", "")
        def_port = str(cfg.get("port", ""))
        def_user = cfg.get("user", "")
        def_pass = cfg.get("password", "")
        def_path = cfg.get("remote_path", "/")

    print_info("提示：直接回车将保留默认值/当前值")

    proto = ask_input(f"传输协议 (ftp/sftp) [当前: [magenta]{def_proto}[/magenta]]") or def_proto
    proto = proto.lower()
    if proto not in ["ftp", "sftp"]:
        print_error("无效的协议，仅支持 ftp 或 sftp")
        return False

    if not def_port:
        def_port = "21" if proto == "ftp" else "22"

    host = ask_input(f"主机地址 [当前: [magenta]{def_host}[/magenta]]") or def_host
    port = ask_input(f"端口号 [当前: [magenta]{def_port}[/magenta]]") or def_port
    user = ask_input(f"账户 [当前: [magenta]{def_user}[/magenta]]") or def_user
    password = ask_input(f"密码 [当前: [magenta]{'******' if def_pass else '未设置'}[/magenta]]") or def_pass

    print_info(r"提示：翼龙面板(Pterodactyl)主机用户请将远程路径设为 / 或留空")
    remote_path = ask_input(f"远程路径 [当前: [magenta]{def_path}[/magenta]]\n⏳ 请输入") or def_path

    config_data = {
        proto: {
            "host": host,
            "port": int(port) if port.isdigit() else (21 if proto == "ftp" else 22),
            "user": user,
            "password": password,
            "remote_path": normalize_path(remote_path),
        }
    }

    try:
        with open(project_path / "server.json", "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4, ensure_ascii=False)
        print_success("主机配置已保存到 server.json")
        return True
    except Exception as e:
        print_error(f"保存配置失败: {e}")
        return False
