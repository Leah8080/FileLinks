import time
from pathlib import Path
from src.ui import print_info, print_success, print_error, print_warning, print_step, ask_confirm, ask_input, console
from src.sync.scanner import get_local_structure
from src.sync.engine import generate_bidirectional_plan, generate_one_way_plan, generate_sync_plan
from src.sync.comm import fetch_remote_state, run_sync_action, get_real_remote_structure
from src.sync.view import display_bidirectional_sync_tree, display_sync_tree, display_remote_tree
from src.filter import get_ignore_spec
from src.sync.host import get_server_config, manage_host_config
from src.sync.logging import log_action
from src.sync.remote import resolve_remote_target as _resolve_remote_target
from src.sync.remote import scan_remote_structure as _scan_remote_structure
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


def _with_state_hashes(real_struct, state_struct):
    """用状态缓存中的 hash 补全真实扫描结果。"""
    if not real_struct or not state_struct:
        return real_struct
    merged = {}
    for path, info in real_struct.items():
        merged_info = dict(info)
        state_info = state_struct.get(path)
        if (
            state_info
            and info.get("type") == state_info.get("type")
            and info.get("size") == state_info.get("size")
            and state_info.get("md5")
        ):
            merged_info["md5"] = state_info["md5"]
        merged[path] = merged_info
    return merged


def smart_sync(project_path: Path, spec):
    """智能同步：自动判断增量更新"""
    started_at = time.perf_counter()
    config = get_server_config(project_path)
    if not config: return False
    protocol, cfg = config
    scan_meta = {"remote_scan": False}

    local_ignored = {}
    local_struct = get_local_structure(project_path, project_path, spec, local_ignored)
    local_state, _ = _load_filtered_local_state(project_path, spec)
    remote_state = fetch_remote_state(protocol, cfg)
    remote_state, remote_ignored = _filter_structure(remote_state, spec)

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

    if not local_state:
        print_warning("本地无同步记录。请使用“强制推送”或“强制拉取”初始化状态。")
        return False
    
    if not remote_state or (local_state and remote_state != local_state):
        remote_target, real_remote_ignored = _resolve_remote_target(protocol, cfg, local_state, remote_state, spec, scan_meta)
        remote_state = _with_state_hashes(remote_target, remote_state)
        remote_ignored = _merge_ignored(remote_ignored, real_remote_ignored)

    remote_state = remote_state or {}
    plan, path_states, stats = generate_bidirectional_plan(local_struct, remote_state, local_state)
    filtered_paths = _merge_ignored(remote_ignored, local_ignored)

    display_bidirectional_sync_tree(path_states, local_struct, remote_state, project_path.name, stats, filtered_paths)

    if stats.get("conflict"):
        print_warning(f"检测到 {stats['conflict']} 处冲突。智能同步不会自动覆盖冲突项，请使用强制推送或强制拉取处理。")
        return False

    has_changes = any(plan[key] for key in ("upload", "download", "delete_remote", "delete_local", "pre_delete_remote", "pre_delete_local"))
    if not has_changes:
        print_success("本地与远程已同步，无需操作。")
        return True

    if _confirm_sync_plan("确认执行双向同步计划？") != "run":
        return False

    success = True
    if plan["upload"] or plan["delete_remote"] or plan["pre_delete_remote"]:
        upload_plan = {
            "upload": plan["upload"],
            "delete": plan["delete_remote"],
            "pre_delete": plan["pre_delete_remote"],
            "skip": [],
        }
        success = run_sync_action(project_path, cfg, protocol, upload_plan, local_struct, is_download=False, spec=spec) and success

    if success and (plan["download"] or plan["delete_local"] or plan["pre_delete_local"]):
        download_plan = {
            "upload": plan["download"],
            "delete": plan["delete_local"],
            "pre_delete": plan["pre_delete_local"],
            "skip": [],
        }
        success = run_sync_action(project_path, cfg, protocol, download_plan, remote_state, is_download=True, spec=spec) and success

    failed_count = run_sync_action.last_result.get("failed", 0)
    log_action(
        project_path, "Smart Sync", stats, direction="bidirectional", force=False,
        filtered_count=len(filtered_paths), failed_count=failed_count,
        elapsed=time.perf_counter() - started_at, remote_scan=scan_meta["remote_scan"],
        status="success" if success else "failed"
    )
    if success:
        new_local = get_local_structure(project_path, project_path, spec)
        clean_state = _save_clean_state(project_path, new_local, spec)
        _push_clean_remote_state(protocol, cfg, clean_state, spec)
        print_success("智能同步成功！")
        return True
    return False

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
        print_warning("⚠️ [bold red]强制上传模式[/bold red]：将以本地文件为准，差异覆盖远程内容。")
        with console.status("[cyan]扫描远程结构..."):
            scan_meta["remote_scan"] = True
            remote_target, real_remote_ignored = _scan_remote_structure(protocol, cfg, spec)
        remote_target = _with_state_hashes(remote_target, remote_state)
        remote_ignored = _merge_ignored(remote_ignored, real_remote_ignored)
        plan, path_states, stats = generate_one_way_plan(local_struct, remote_target, delete_extras=True)
        filtered_paths = _merge_ignored(state_ignored, remote_ignored, local_ignored)
        display_sync_tree(
            path_states,
            local_struct,
            remote_target,
            project_path.name,
            stats,
            filtered_paths=filtered_paths,
            added_label="待上传"
        )
        if not (plan["upload"] or plan["delete"] or plan.get("pre_delete")):
            print_success("远程已与本地一致，无需传输。")
            clean_state = _save_clean_state(project_path, local_struct, spec)
            _push_clean_remote_state(protocol, cfg, clean_state, spec)
            return True
        confirm = _confirm_sync_plan("确认以本地为准覆盖远程吗？远程多余文件将被删除，被忽略文件会保留")
        if confirm != "run":
            return False
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
            print_success("强制推送完成！")
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

    if force:
        print_warning("⚠️ [bold red]强制下载模式[/bold red]：将以云端文件为准，差异覆盖本地内容。")
        remote_cache = remote_state
        with console.status("[cyan]扫描远程结构..."):
            scan_meta["remote_scan"] = True
            remote_state, real_remote_ignored = _scan_remote_structure(protocol, cfg, spec)
        remote_state = _with_state_hashes(remote_state, remote_cache)
        remote_ignored = _merge_ignored(remote_ignored, real_remote_ignored)
        local_ignored = {}
        local_struct = get_local_structure(project_path, project_path, spec, local_ignored)
        plan, path_states, stats = generate_one_way_plan(remote_state, local_struct, delete_extras=True)
    else:
        remote_state, real_remote_ignored = _resolve_remote_target(protocol, cfg, local_state, remote_state, spec, scan_meta)
        remote_ignored = _merge_ignored(remote_ignored, real_remote_ignored)
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
        if force:
            current_local = get_local_structure(project_path, project_path, spec)
            _save_clean_state(project_path, current_local, spec)
        else:
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
