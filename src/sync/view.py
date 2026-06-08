from pathlib import Path
from rich.tree import Tree
from rich.panel import Panel
from rich.markup import escape
from src.ui import console
from src.config_loader import load_config

def _ensure_parent_node(nodes, parent_path):
    if not parent_path or parent_path in nodes:
        return
    parts = parent_path.split("/")
    grandparent = "/".join(parts[:-1])
    _ensure_parent_node(nodes, grandparent)
    nodes[parent_path] = nodes[grandparent].add(f"[dim]📁 {parts[-1]}[/dim]")

def _format_filtered_summary(filtered_paths):
    counts = {"local": 0, "remote": 0, "state": 0}
    for info in filtered_paths.values():
        origins = str(info.get("origin", "")).split("+")
        for origin in origins:
            if origin in counts:
                counts[origin] += 1
    parts = []
    if counts["local"]:
        parts.append(f"本地 {counts['local']}")
    if counts["remote"]:
        parts.append(f"远程 {counts['remote']}")
    if counts["state"]:
        parts.append(f"状态 {counts['state']}")
    detail = f" ({' / '.join(parts)})" if parts else ""
    return f"  [dim]⊘ {len(filtered_paths)} 已过滤{detail}[/dim]"

def _filtered_label(info):
    source = info.get("ignored_by")
    if source:
        return f"[已过滤: {escape(str(source))}]"
    return "[已过滤]"

def display_sync_tree(path_states, source_struct, target_struct, project_name, stats, is_download=False, filtered_paths=None, added_label=None):
    """显示优化的同步预览树"""
    filtered_paths = filtered_paths or {}
    action_text = "下载" if is_download else "上传"
    added_label = added_label or f"待{action_text}"
    summary = f"[bold green]+ {stats['added']} {added_label}[/bold green]  " \
              f"[bold yellow]~ {stats['updated']} 待更新[/bold yellow]  " \
              f"[bold red]- {stats['deleted']} 待删除[/bold red]"
    if stats.get("conflict"):
        summary += f"  [bold magenta]! {stats['conflict']} 冲突[/bold magenta]"
    if filtered_paths:
        summary += _format_filtered_summary(filtered_paths)
        
    console.print(Panel(summary, title="📊 同步摘要", expand=False))
    
    tree = Tree(f"[bold blue]📁 {project_name}[/bold blue]")
    nodes = {"": tree}
    all_paths = sorted(set(path_states.keys()) | set(filtered_paths.keys()))
    
    config = load_config()
    icon_map = config.get("icons", {})

    for path in all_paths:
        parts = path.split("/")
        parent = "/".join(parts[:-1])
        name = parts[-1]
        
        state = "filtered" if path in filtered_paths else path_states[path]
        
        style, label = "dim", ""
        if state == "added":
            style, label = "bold green", f"[待{action_text}]"
        elif state == "deleted":
            style, label = "bold red", "[待删除]"
        elif state == "updated":
            style, label = "bold yellow", "[待更新]"
        elif state == "conflict":
            style, label = "bold magenta", "[冲突]"
        elif state == "filtered":
            style, label = "dim", _filtered_label(filtered_paths[path])
            
        info = source_struct.get(path) or target_struct.get(path) or filtered_paths.get(path)
        is_dir = info["type"] == "dir"
        
        if is_dir:
            icon = "📁"
        else:
            ext = Path(name).suffix.lower()
            icon = icon_map.get(ext, "📄")
        
        display_text = f"[{style}]{icon} {name} {label}[/{style}]"
        
        _ensure_parent_node(nodes, parent)
        nodes[path] = nodes[parent].add(display_text)
            
    console.print(tree)

def display_remote_tree(remote_struct, project_name, filtered_paths=None):
    """显示远程主机的文件树结构"""
    filtered_paths = filtered_paths or {}
    tree = Tree(f"[bold blue]🖥️ 远程主机: {project_name}[/bold blue]")
    nodes = {"": tree}
    all_paths = sorted(set(remote_struct.keys()) | set(filtered_paths.keys()))
    
    config = load_config()
    icon_map = config.get("icons", {})

    for path in all_paths:
        parts = path.split("/")
        parent = "/".join(parts[:-1])
        name = parts[-1]
        
        is_filtered = path in filtered_paths
        info = filtered_paths[path] if is_filtered else remote_struct[path]
        is_dir = info["type"] == "dir"
        
        if is_filtered:
            icon = "📁" if is_dir else icon_map.get(Path(name).suffix.lower(), "📄")
            style = "dim"
        elif is_dir:
            icon = "📁"
            style = "bold blue"
        else:
            ext = Path(name).suffix.lower()
            icon = icon_map.get(ext, "📄")
            style = "green"
        
        size_str = f" [dim]({info['size']} bytes)[/dim]" if not is_dir and not is_filtered else ""
        label = f" {_filtered_label(info)}" if is_filtered else ""
        display_text = f"[{style}]{icon} {name}{label}[/{style}]{size_str}"
        
        _ensure_parent_node(nodes, parent)
        nodes[path] = nodes[parent].add(display_text)
            
    console.print(Panel(tree, title="🌳 远程文件树预览", border_style="cyan", expand=False))
