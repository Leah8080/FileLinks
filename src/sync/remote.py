from src.config_loader import load_config
from src.sync.comm import get_real_remote_structure
from src.ui import console, print_warning


def scan_remote_structure(protocol, cfg, spec):
    remote_ignored = {}
    remote_struct = get_real_remote_structure(protocol, cfg, spec, remote_ignored)
    return remote_struct, remote_ignored


def resolve_remote_target(protocol, cfg, local_state, remote_state, spec, scan_meta=None):
    if remote_state is None:
        with console.status("[cyan]扫描远程结构..."):
            if scan_meta is not None:
                scan_meta["remote_scan"] = True
            return scan_remote_structure(protocol, cfg, spec)
    if local_state and remote_state != local_state:
        if load_config().get("remote_scan_on_state_mismatch", True):
            print_warning("⚠️ 远程状态与本地记录不一致，正在扫描真实远程结构重新校验。")
            with console.status("[cyan]扫描远程结构..."):
                if scan_meta is not None:
                    scan_meta["remote_scan"] = True
                return scan_remote_structure(protocol, cfg, spec)
        print_warning("⚠️ 远程状态与本地记录不一致；已按配置跳过真实远程扫描。")
    return remote_state, {}
