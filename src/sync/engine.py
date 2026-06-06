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
