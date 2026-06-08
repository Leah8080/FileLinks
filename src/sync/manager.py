import time
from pathlib import Path
from src.ui import print_info, print_success, print_error, print_warning, ask_confirm, ask_input, console
from src.sync.scanner import get_local_structure
from src.sync.engine import generate_sync_plan
from src.sync.comm import fetch_remote_state, wipe_remote, run_sync_action, get_real_remote_structure
from src.sync.view import display_sync_tree, display_remote_tree
from src.filter import get_ignore_spec
from src.sync.host import get_server_config, manage_host_config
from src.sync.logging import log_action
from src.sync.remote import resolve_remote_target as _resolve_remote_target
from src.sync.remote import scan_remote_structure as _scan_remote_structure
from src.sync.state import count_files as _count_files
from src.sync.state import filter_structure as _filter_structure
from src.sync.state import load_filtered_local_state as _load_filtered_local_state
from src.sync.state import merge_ignored as _merge_ignored
from src.sync.state import push_clean_remote_state as _push_clean_remote_state
from src.sync.state import save_clean_state as _save_clean_state

def _confirm_sync_plan(prompt):
    choice = ask_input(f"{prompt} ([bold green]Y[/bold green]执行 / [bold yellow]P[/bold yellow]仅预览 / [bold red]N[/bold red]取消)").upper()
    if choice == "Y":
        return "run"
    if choice == "P":
        print_info("预览结束，未执行任何操作。")
        return "preview"
    return "cancel"


def smart_sync(project_path: Path, spec):
    """智能同步：自动判断增量更新"""
    config = get_server_config(project_path)
    if not config: return False
    protocol, cfg = config

    local_struct = get_local_structure(project_path, project_path, spec)
    local_state, _ = _load_filtered_local_state(project_path, spec)
    remote_state = fetch_remote_state(protocol, cfg)
    remote_state, _ = _filter_structure(remote_state, spec)

    # 1. 如果两边都没有状态，引导首次同步
    if not local_state and not remote_state:
        print_warning("检测到首次同步。")
        choice = ask_input("是以本地为准[bold green]上传(U)[/bold green]，还是以云端为准[bold cyan]下载(D)[/bold cyan]？(U/D)")
        if choice.upper() == 'U':
            return sync_to_remote(project_path, spec, force=True)
        elif choice.upper() == 'D':
            return sync_from_remote(project_path, spec, force=True)
        return False

    print_info("正在分析增量更新...")
    
    if not remote_state or (local_state and remote_state != local_state):
        remote_state, _ = _resolve_remote_target(protocol, cfg, local_state, remote_state, spec)

    return sync_to_remote(project_path, spec, force=False)

def sync_to_remote(project_path: Path, spec, force=False):
    started_at = time.perf_counter()
    config = get_server_config(project_path)
    if not config: return False
    protocol, cfg = config
    scan_meta = {"remote_scan": False}

    local_ignored = {}
    local_struct = get_local_structure(project_path, project_path, spec, local_ignored)
    local_state, state_ignored = _load_filtered_local_state(project_path, spec)
    remote_state = fetch_remote_state(protocol, cfg)
    remote_state, remote_ignored = _filter_structure(remote_state, spec)

    if force:
        print_warning("⚠️ [bold red]强制上传模式[/bold red]：将以本地文件为准，覆盖远程内容。")
        path_states = {path: "added" for path in local_struct}
        stats = {"added": _count_files(local_struct), "updated": 0, "deleted": 0, "conflict": 0}
        filtered_paths = _merge_ignored(state_ignored, remote_ignored, local_ignored)
        display_sync_tree(
            path_states,
            local_struct,
            {},
            project_path.name,
            stats,
            filtered_paths=filtered_paths,
            added_label="将重建远程"
        )
        confirm = _confirm_sync_plan("确认清空远程并重新上传吗？被忽略的远程文件会保留")
        if confirm != "run":
            return False
        if wipe_remote(protocol, cfg, spec):
            plan = {"upload": sorted(local_struct.keys()), "delete": [], "skip": []}
            success = run_sync_action(project_path, cfg, protocol, plan, local_struct, is_download=False, spec=spec)
            failed_count = run_sync_action.last_result.get("failed", 0)
            log_action(
                project_path, "Force Upload", stats, direction="upload", force=True,
                filtered_count=len(filtered_paths), failed_count=failed_count,
                elapsed=time.perf_counter() - started_at, remote_scan=scan_meta["remote_scan"],
                status="success" if success else "failed"
            )
            if success:
                clean_state = _save_clean_state(project_path, local_struct, spec)
                _push_clean_remote_state(protocol, cfg, clean_state, spec)
                print_success("首次同步完成！")
                return True
        return False

    if not local_state:
        print_warning("本地无同步记录。请使用“强制上传”或先执行“强制下载”初始化状态。")
        return False

    target_for_plan, real_remote_ignored = _resolve_remote_target(protocol, cfg, local_state, remote_state, spec, scan_meta)
    remote_ignored = _merge_ignored(remote_ignored, real_remote_ignored)
    target_for_plan = target_for_plan if target_for_plan is not None else local_state
    plan, path_states, stats = generate_sync_plan(local_struct, target_for_plan, base_struct=local_state)
    filtered_paths = _merge_ignored(state_ignored, remote_ignored, local_ignored)
    
    display_sync_tree(path_states, local_struct, target_for_plan, project_path.name, stats, filtered_paths=filtered_paths)

    if stats.get("conflict"):
        print_warning(f"检测到 {stats['conflict']} 处冲突！")
        if not ask_confirm("冲突项将以本地为准进行覆盖，是否继续？"):
            return False
            
    if not (plan["upload"] or plan["delete"]):
        print_success("本地与远程已同步，无需操作。")
        log_action(
            project_path, "Incremental Sync", stats, direction="upload", force=False,
            filtered_count=len(filtered_paths), elapsed=time.perf_counter() - started_at,
            remote_scan=scan_meta["remote_scan"], status="no-op"
        )
        return True

    confirm = _confirm_sync_plan("确认执行同步计划？")
    if confirm == "run":
        success = run_sync_action(project_path, cfg, protocol, plan, local_struct, is_download=False, spec=spec)
        failed_count = run_sync_action.last_result.get("failed", 0)
        log_action(
            project_path, "Incremental Sync", stats, direction="upload", force=False,
            filtered_count=len(filtered_paths), failed_count=failed_count,
            elapsed=time.perf_counter() - started_at, remote_scan=scan_meta["remote_scan"],
            status="success" if success else "failed"
        )
        if success:
            clean_state = _save_clean_state(project_path, local_struct, spec)
            _push_clean_remote_state(protocol, cfg, clean_state, spec)
            print_success("同步成功！")
            return True
    return False

def sync_from_remote(project_path: Path, spec, force=False):
    started_at = time.perf_counter()
    config = get_server_config(project_path)
    if not config: return False
    protocol, cfg = config
    scan_meta = {"remote_scan": False}

    local_state, state_ignored = _load_filtered_local_state(project_path, spec)
    remote_state = fetch_remote_state(protocol, cfg)
    remote_state, remote_ignored = _filter_structure(remote_state, spec)
    remote_state, real_remote_ignored = _resolve_remote_target(protocol, cfg, local_state, remote_state, spec, scan_meta)
    remote_ignored = _merge_ignored(remote_ignored, real_remote_ignored)

    if force:
        print_warning("⚠️ [bold red]强制下载模式[/bold red]：将以云端文件为准，覆盖本地内容。")
        local_ignored = {}
        local_struct = get_local_structure(project_path, project_path, spec, local_ignored)
        plan, path_states, stats = generate_sync_plan(remote_state, local_struct, local_state)
    else:
        if not local_state:
            print_warning("本地无记录，请使用“强制下载”。")
            return False
        local_ignored = {}
        local_struct = get_local_structure(project_path, project_path, spec, local_ignored)
        plan, path_states, stats = generate_sync_plan(remote_state, local_struct, local_state)

    filtered_paths = _merge_ignored(state_ignored, local_ignored, remote_ignored)
    display_sync_tree(path_states, remote_state, local_struct, project_path.name, stats, is_download=True, filtered_paths=filtered_paths)

    if not (plan["upload"] or plan["delete"]):
        print_success("本地已是最新，无需操作。")
        _save_clean_state(project_path, remote_state, spec)
        log_action(
            project_path,
            "Force Download" if force else "Download Sync",
            stats,
            direction="download",
            force=force,
            filtered_count=len(filtered_paths),
            elapsed=time.perf_counter() - started_at,
            remote_scan=scan_meta["remote_scan"],
            status="no-op"
        )
        return True

    confirm_message = "确认同步云端到本地吗？本地多余文件将被删除" if force else "确认同步？"
    if _confirm_sync_plan(confirm_message) == "run":
        success = run_sync_action(project_path, cfg, protocol, plan, remote_state, is_download=True, spec=spec)
        failed_count = run_sync_action.last_result.get("failed", 0)
        log_action(
            project_path,
            "Force Download" if force else "Download Sync",
            stats,
            direction="download",
            force=force,
            filtered_count=len(filtered_paths),
            failed_count=failed_count,
            elapsed=time.perf_counter() - started_at,
            remote_scan=scan_meta["remote_scan"],
            status="success" if success else "failed"
        )
        if success:
            new_local = get_local_structure(project_path, project_path, spec)
            clean_state = _save_clean_state(project_path, new_local, spec)
            _push_clean_remote_state(protocol, cfg, clean_state, spec)
            return True
    return False

def preview_remote_structure(project_path: Path):
    """获取并显示远程主机的文件树预览"""
    config = get_server_config(project_path)
    if not config:
        print_error("未配置远程主机信息，请先进行“主机配置”。")
        return False
    
    protocol, cfg = config
    spec = get_ignore_spec(project_path)
    print_step(f"正在连接远程主机 ({protocol.upper()}) 并获取文件树...")
    
    try:
        with console.status("[cyan]正在扫描远程文件系统..."):
            remote_ignored = {}
            remote_struct = get_real_remote_structure(protocol, cfg, spec, remote_ignored)
        
        if not remote_struct and not remote_ignored:
            print_warning("远程目录为空或无法读取。")
            return True
        
        display_remote_tree(remote_struct, project_path.name, remote_ignored)
        return True
    except Exception as e:
        print_error(f"无法获取远程结构: {e}")
        return False
