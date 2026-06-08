import time
from pathlib import Path

from src.sync.scanner import SYNC_LOG_FILENAME


def log_action(
    project_path: Path,
    action_type: str,
    stats: dict,
    direction: str = "-",
    force: bool = False,
    filtered_count: int = 0,
    failed_count: int = 0,
    elapsed: float | None = None,
    remote_scan: bool = False,
    status: str = "success",
):
    """记录同步操作到 .sync_log"""
    log_file = project_path / SYNC_LOG_FILENAME
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    elapsed_text = f"{elapsed:.2f}s" if elapsed is not None else "-"
    log_entry = (
        f"[{timestamp}] {action_type} | status={status} | direction={direction} | force={force} | "
        f"+{stats.get('added', 0)} added | ~{stats.get('updated', 0)} updated | "
        f"-{stats.get('deleted', 0)} deleted | !{stats.get('conflict', 0)} conflict | "
        f"filtered={filtered_count} | failed={failed_count} | remote_scan={remote_scan} | "
        f"elapsed={elapsed_text}\n"
    )
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except Exception:
        pass
