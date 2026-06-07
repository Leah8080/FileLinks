from pathlib import Path
from rich.tree import Tree
from rich.panel import Panel
from src.ui import console
from src.config_loader import load_config

def display_sync_tree(path_states, source_struct, target_struct, project_name, stats, is_download=False):
    """显示优化的同步预览树"""
    action_text = "下载" if is_download else "上传"
    summary = f"[bold green]+ {stats['added']} 待{action_text}[/bold green]  " \
              f"[bold yellow]~ {stats['updated']} 待更新[/bold yellow]  " \
              f"[bold red]- {stats['deleted']} 待删除[/bold red]"
    if stats.get("conflict"):
        summary += f"  [bold magenta]! {stats['conflict']} 冲突[/bold magenta]"
        
    console.print(Panel(summary, title="📊 同步摘要", expand=False))
    
    tree = Tree(f"[bold blue]📁 {project_name}[/bold blue]")
    nodes = {"": tree}
    all_paths = sorted(path_states.keys())
    
    config = load_config()
    icon_map = config.get("icons", {})

    for path in all_paths:
        parts = path.split("/")
        parent = "/".join(parts[:-1])
        name = parts[-1]
        
        state = path_states[path]
        
        style, label = "dim", ""
        if state == "added":
            style, label = "bold green", f"[待{action_text}]"
        elif state == "deleted":
            style, label = "bold red", "[待删除]"
        elif state == "updated":
            style, label = "bold yellow", "[待更新]"
        elif state == "conflict":
            style, label = "bold magenta", "[冲突]"
            
        is_dir = (source_struct.get(path) or target_struct.get(path))["type"] == "dir"
        
        if is_dir:
            icon = "📁"
        else:
            ext = Path(name).suffix.lower()
            icon = icon_map.get(ext, "📄")
        
        display_text = f"[{style}]{icon} {name} {label}[/{style}]"
        
        if parent in nodes:
            nodes[path] = nodes[parent].add(display_text)
            
    console.print(tree)

def display_remote_tree(remote_struct, project_name):
    """显示远程主机的文件树结构"""
    tree = Tree(f"[bold blue]🖥️ 远程主机: {project_name}[/bold blue]")
    nodes = {"": tree}
    all_paths = sorted(remote_struct.keys())
    
    config = load_config()
    icon_map = config.get("icons", {})

    for path in all_paths:
        parts = path.split("/")
        parent = "/".join(parts[:-1])
        name = parts[-1]
        
        info = remote_struct[path]
        is_dir = info["type"] == "dir"
        
        if is_dir:
            icon = "📁"
            style = "bold blue"
        else:
            ext = Path(name).suffix.lower()
            icon = icon_map.get(ext, "📄")
            style = "green"
        
        size_str = f" [dim]({info['size']} bytes)[/dim]" if not is_dir else ""
        display_text = f"[{style}]{icon} {name}[/{style}]{size_str}"
        
        if parent in nodes:
            nodes[path] = nodes[parent].add(display_text)
            
    console.print(Panel(tree, title="🌳 远程文件树预览", border_style="cyan", expand=False))
