from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt
from rich import print as rprint

console = Console()

def print_success(message: str):
    console.print(f"[bold green]✅ {message}[/bold green]")

def print_info(message: str):
    console.print(f"[cyan]📝 {message}[/cyan]")

def print_warning(message: str):
    console.print(f"[bold yellow]🚨 {message}[/bold yellow]")

def print_error(message: str):
    console.print(f"[bold red]❌ {message}[/bold red]")

def print_step(message: str):
    console.print(f"\n[bold blue]➡️  {message}[/bold blue]")

def print_summary(total: int, links: int, filtered: int):
    table = Table(title="📊 摘要信息", show_header=True, header_style="bold magenta")
    table.add_column("分类", style="dim")
    table.add_column("数量", justify="right")
    table.add_row("文件总数", str(total))
    table.add_row("生成链接", str(links))
    table.add_row("已过滤", str(filtered))
    console.print(table)

def print_menu(title: str, options: list):
    """
    打印一个带标题的菜单
    """
    menu_text = ""
    for i, option in enumerate(options, 1):
        menu_text += f"[bold blue]{i}.[/bold blue] {option}\n"
    
    console.print(Panel(menu_text.strip(), title=f"[bold cyan]{title}[/bold cyan]", border_style="cyan", expand=False))

def ask_input(prompt: str) -> str:
    return Prompt.ask(f"[bold cyan]✏️  {prompt}[/bold cyan]")

def print_header(title: str):
    from rich.align import Align
    console.print(Panel(Align.center(f"[bold magenta]{title}[/bold magenta]"), style="bold blue", expand=True))

def print_server_info(protocol: str, config: dict):
    table = Table(title=f"🖥️ 目标服务器信息 ({protocol.upper()})", show_header=False, border_style="yellow")
    table.add_column("Key", style="bold cyan")
    table.add_column("Value")
    table.add_row("主机", config.get("host"))
    table.add_row("端口", str(config.get("port", 21 if protocol == "ftp" else 22)))
    table.add_row("用户", config.get("user"))
    table.add_row("远程路径", config.get("remote_path", "/"))
    console.print(table)

def ask_confirm(prompt: str) -> bool:
    from rich.prompt import Confirm
    return Confirm.ask(f"[bold yellow]{prompt}[/bold yellow]")
