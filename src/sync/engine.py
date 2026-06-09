def _same_entry(left, right, allow_size_only=True):
    if not left or not right:
        return False
    if left.get("type") != right.get("type"):
        return False
    if left.get("type") == "dir":
        return True
    if left.get("size") != right.get("size"):
        return False
    left_md5 = left.get("md5")
    right_md5 = right.get("md5")
    if left_md5 and right_md5:
        return left_md5 == right_md5
    return allow_size_only


def _is_changed(current_struct, base_struct, path):
    current = current_struct.get(path)
    base = base_struct.get(path)
    if current is None and base is None:
        return False
    if current is None or base is None:
        return True
    return not _same_entry(current, base)


def _count_file(struct, path):
    return 1 if struct.get(path, {}).get("type") == "file" else 0


def _is_descendant(path, parent):
    return path != parent and path.startswith(f"{parent}/")


def generate_one_way_plan(source_struct, target_struct, delete_extras=True, allow_size_only=False):
    """生成 source -> target 的差异覆盖计划。"""
    all_paths = sorted(set(source_struct.keys()) | set(target_struct.keys()))
    replace_roots = {
        path
        for path in all_paths
        if path in source_struct
        and path in target_struct
        and source_struct[path].get("type") != target_struct[path].get("type")
    }
    plan = {"upload": [], "delete": [], "pre_delete": [], "skip": [], "conflict": []}
    stats = {"added": 0, "updated": 0, "deleted": 0, "conflict": 0}
    path_states = {}

    for path in all_paths:
        source = source_struct.get(path)
        target = target_struct.get(path)
        replaced_parent = next((root for root in replace_roots if _is_descendant(path, root)), None)

        if replaced_parent and target:
            plan["pre_delete"].append(path)
            path_states[path] = "deleted"
            stats["deleted"] += _count_file(target_struct, path)
            continue

        if source and not target:
            plan["upload"].append(path)
            path_states[path] = "added"
            stats["added"] += _count_file(source_struct, path)
            continue

        if target and not source:
            if delete_extras:
                plan["delete"].append(path)
                path_states[path] = "deleted"
                stats["deleted"] += _count_file(target_struct, path)
            else:
                plan["skip"].append(path)
                path_states[path] = "none"
            continue

        if not source or not target:
            continue

        if source.get("type") != target.get("type"):
            plan["pre_delete"].append(path)
            plan["upload"].append(path)
            path_states[path] = "updated"
            stats["updated"] += _count_file(source_struct, path)
            continue

        if _same_entry(source, target, allow_size_only=allow_size_only):
            plan["skip"].append(path)
            path_states[path] = "none"
            continue

        if source.get("type") == "file":
            plan["upload"].append(path)
            path_states[path] = "updated"
            stats["updated"] += 1
        else:
            plan["skip"].append(path)
            path_states[path] = "none"

    return plan, path_states, stats


def generate_bidirectional_plan(local_struct, remote_struct, base_struct):
    """基于上次同步状态生成双向同步计划。"""
    all_paths = sorted(set(local_struct.keys()) | set(remote_struct.keys()) | set(base_struct.keys()))
    plan = {
        "upload": [],
        "download": [],
        "delete_remote": [],
        "delete_local": [],
        "pre_delete_remote": [],
        "pre_delete_local": [],
        "skip": [],
        "conflict": [],
    }
    stats = {
        "upload": 0,
        "download": 0,
        "delete_remote": 0,
        "delete_local": 0,
        "conflict": 0,
    }
    path_states = {}

    for path in all_paths:
        local = local_struct.get(path)
        remote = remote_struct.get(path)
        local_changed = _is_changed(local_struct, base_struct, path)
        remote_changed = _is_changed(remote_struct, base_struct, path)

        if local_changed and remote_changed:
            if (local is None and remote is None) or _same_entry(local, remote):
                plan["skip"].append(path)
                path_states[path] = "none"
                continue
            plan["conflict"].append(path)
            path_states[path] = "conflict"
            stats["conflict"] += 1
            continue

        if local_changed:
            if local is None:
                plan["delete_remote"].append(path)
                path_states[path] = "delete_remote"
                stats["delete_remote"] += _count_file(remote_struct, path)
            elif remote is None:
                plan["upload"].append(path)
                path_states[path] = "upload"
                stats["upload"] += _count_file(local_struct, path)
            elif local.get("type") != remote.get("type"):
                plan["pre_delete_remote"].append(path)
                plan["upload"].append(path)
                path_states[path] = "upload"
                stats["upload"] += _count_file(local_struct, path)
            elif not _same_entry(local, remote):
                plan["upload"].append(path)
                path_states[path] = "upload"
                stats["upload"] += _count_file(local_struct, path)
            else:
                plan["skip"].append(path)
                path_states[path] = "none"
            continue

        if remote_changed:
            if remote is None:
                plan["delete_local"].append(path)
                path_states[path] = "delete_local"
                stats["delete_local"] += _count_file(local_struct, path)
            elif local is None:
                plan["download"].append(path)
                path_states[path] = "download"
                stats["download"] += _count_file(remote_struct, path)
            elif remote.get("type") != local.get("type"):
                plan["pre_delete_local"].append(path)
                plan["download"].append(path)
                path_states[path] = "download"
                stats["download"] += _count_file(remote_struct, path)
            elif not _same_entry(remote, local):
                plan["download"].append(path)
                path_states[path] = "download"
                stats["download"] += _count_file(remote_struct, path)
            else:
                plan["skip"].append(path)
                path_states[path] = "none"
            continue

        plan["skip"].append(path)
        path_states[path] = "none"

    return plan, path_states, stats


def generate_sync_plan(source_struct, target_struct, cache_struct=None, base_struct=None):
    """
    对比两端结构，生成同步计划。
    base_struct: 上次同步时的状态，用于冲突检测。
    """
    if cache_struct is None: cache_struct = {}
    if base_struct is None: base_struct = {}
    
    all_paths = sorted(list(set(source_struct.keys()) | set(target_struct.keys())))
    plan = {"upload": [], "delete": [], "skip": [], "conflict": []}
    stats = {"added": 0, "updated": 0, "deleted": 0, "conflict": 0}
    path_states = {}
    
    for path in all_paths:
        # 基础冲突检测逻辑：
        # 如果 source 和 target 都相对于 base 发生了变化，且变化结果不同，则为冲突。
        is_source_changed = False
        is_target_changed = False
        
        if path in source_struct:
            if path not in base_struct: is_source_changed = True
            elif source_struct[path].get("md5") != base_struct[path].get("md5"): is_source_changed = True
            elif source_struct[path].get("size") != base_struct[path].get("size"): is_source_changed = True
            
        if path in target_struct:
            if path not in base_struct: is_target_changed = True
            elif target_struct[path].get("md5") != base_struct[path].get("md5"): is_target_changed = True
            elif target_struct[path].get("size") != base_struct[path].get("size"): is_target_changed = True
            
        # 路径删除也被视为变化
        if path in base_struct and path not in source_struct: is_source_changed = True
        if path in base_struct and path not in target_struct: is_target_changed = True

        if is_source_changed and is_target_changed:
            # 进一步判断是否真的冲突（比如两边改成了同样的内容，则不算冲突）
            content_match = False
            if path in source_struct and path in target_struct:
                if source_struct[path].get("md5") == target_struct[path].get("md5") and \
                   source_struct[path].get("size") == target_struct[path].get("size"):
                    content_match = True
            elif path not in source_struct and path not in target_struct:
                content_match = True
                
            if not content_match:
                plan["conflict"].append(path)
                path_states[path] = "conflict"
                stats["conflict"] += 1
                continue

        # 正常的增量判断
        if path in source_struct and path not in target_struct:
            plan["upload"].append(path)
            path_states[path] = "added"
            if source_struct[path]["type"] == "file": stats["added"] += 1
        elif path not in source_struct and path in target_struct:
            plan["delete"].append(path)
            path_states[path] = "deleted"
            if target_struct[path]["type"] == "file": stats["deleted"] += 1
        elif path in source_struct and path in target_struct:
            if source_struct[path]["type"] == "dir":
                plan["skip"].append(path)
                path_states[path] = "none"
            else:
                is_modified = False
                if source_struct[path]["size"] != target_struct[path]["size"]:
                    is_modified = True
                else:
                    s_md5 = source_struct[path].get("md5")
                    t_md5 = target_struct[path].get("md5")
                    if s_md5 and t_md5 and s_md5 != t_md5:
                        is_modified = True
                    elif s_md5 and not t_md5:
                        c_md5 = cache_struct.get(path, {}).get("md5")
                        if c_md5 and s_md5 != c_md5:
                            is_modified = True
                
                if is_modified:
                    plan["upload"].append(path)
                    path_states[path] = "updated"
                    stats["updated"] += 1
                else:
                    plan["skip"].append(path)
                    path_states[path] = "none"
                
    return plan, path_states, stats
