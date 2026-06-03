import os
import json
import ftplib
import stat
from pathlib import Path
import pathspec
from src.ui import print_info, print_success, print_error, print_warning, print_step, print_server_info, ask_confirm, console
from src.filter import is_ignored

def get_local_structure(path: Path, project_root: Path, spec):
    """获取本地文件结构及基本信息"""
    structure = {}
    for item in path.iterdir():
        if is_ignored(item, project_root, spec, item.is_dir()):
            continue
        
        rel_path = item.relative_to(project_root).as_posix()
        if item.is_dir():
            structure[rel_path] = {"type": "dir", "size": 0}
            structure.update(get_local_structure(item, project_root, spec))
        else:
            structure[rel_path] = {"type": "file", "size": item.stat().st_size}
    return structure

def get_remote_structure_ftp(ftp, current_remote, base_remote):
    """递归获取 FTP 远程结构 (优化版)"""
    structure = {}
    try:
        # 优先尝试使用 mlsd (RFC 3659)，这可以一次性获取类型和大小
        try:
            for name, facts in ftp.mlsd(current_remote):
                if name in (".", ".."): continue
                
                remote_item_path = (Path(current_remote) / name).as_posix()
                try:
                    rel_path = Path(remote_item_path).relative_to(base_remote).as_posix()
                except ValueError:
                    rel_path = remote_item_path.replace(base_remote, "", 1).lstrip("/")

                if facts['type'] == 'dir':
                    structure[rel_path] = {"type": "dir", "size": 0}
                    structure.update(get_remote_structure_ftp(ftp, remote_item_path, base_remote))
                else:
                    size = int(facts.get('size', 0))
                    structure[rel_path] = {"type": "file", "size": size}
            return structure
        except (ftplib.error_perm, AttributeError):
            # 如果服务器不支持 mlsd，退回到 nlst
            items = ftp.nlst(current_remote)
    except ftplib.error_perm:
        return {}

    for remote_item_path in items:
        remote_item_path = remote_item_path.replace("\\", "/")
        name = Path(remote_item_path).name
        if name in (".", ".."): continue

        if not remote_item_path.startswith("/"):
            remote_item_path = (Path(current_remote) / name).as_posix()

        try:
            rel_path = Path(remote_item_path).relative_to(base_remote).as_posix()
        except ValueError:
            rel_path = remote_item_path.replace(base_remote, "", 1).lstrip("/")

        # 退而求其次的类型判断方法
        is_dir = False
        size = 0
        try:
            # 尝试获取大小，如果报错通常是目录
            size = ftp.size(remote_item_path) or 0
        except ftplib.error_perm:
            is_dir = True

        if is_dir:
            structure[rel_path] = {"type": "dir", "size": 0}
            structure.update(get_remote_structure_ftp(ftp, remote_item_path, base_remote))
        else:
            structure[rel_path] = {"type": "file", "size": size}
            
    return structure

def get_remote_structure_sftp(sftp, current_remote, base_remote):
    """递归获取 SFTP 远程结构"""
    import stat
    structure = {}
    try:
        items = sftp.listdir_attr(current_remote)
    except IOError:
        return {}

    for item in items:
        name = item.filename
        if name in (".", ".."): continue
        
        remote_item_path = (Path(current_remote) / name).as_posix()
        try:
            rel_path = Path(remote_item_path).relative_to(base_remote).as_posix()
        except ValueError:
            rel_path = remote_item_path.replace(base_remote, "", 1).lstrip("/")
            
        is_dir = stat.S_ISDIR(item.st_mode)
        if is_dir:
            structure[rel_path] = {"type": "dir", "size": 0}
            structure.update(get_remote_structure_sftp(sftp, remote_item_path, base_remote))
        else:
            structure[rel_path] = {"type": "file", "size": item.st_size}
    return structure

def generate_sync_tree(local_struct, remote_struct, project_name):
    """生成包含同步状态的 Rich 目录树"""
    from rich.tree import Tree
    
    tree = Tree(f"[bold blue]📁 {project_name}[/bold blue] [dim](同步预览)[/dim]")
    
    all_paths = sorted(list(set(local_struct.keys()) | set(remote_struct.keys())))
    nodes = {"": tree}
    
    for path_str in all_paths:
        parts = path_str.split("/")
        parent_path = "/".join(parts[:-1])
        name = parts[-1]
        
        status = ""
        style = ""
        
        if path_str in local_struct and path_str not in remote_struct:
            status = "[待同步]"
            style = "bold green"
        elif path_str not in local_struct and path_str in remote_struct:
            status = "[待删除]"
            style = "bold red"
        elif path_str in local_struct and path_str in remote_struct:
            if local_struct[path_str]["type"] == "dir":
                status = "[未变动]"
                style = "dim"
            elif local_struct[path_str]["size"] == remote_struct[path_str]["size"]:
                status = "[未变动]"
                style = "dim"
            else:
                status = "[待同步]"
                style = "bold yellow"
        
        info = local_struct.get(path_str) or remote_struct.get(path_str)
        icon = "📁" if info["type"] == "dir" else "📄"
        display_text = f"[{style}]{icon} {name} {status}[/{style}]"
        
        if parent_path in nodes:
            nodes[path_str] = nodes[parent_path].add(display_text)
            
    return tree

def load_server_config(project_path: Path):
    server_json_path = project_path / "server.json"
    if not server_json_path.exists():
        raise FileNotFoundError(f"未在项目路径下找到 server.json")
    
    with open(server_json_path, "r", encoding="utf-8") as f:
        return json.load(f)

def sync_files(project_path: Path, spec: pathspec.PathSpec):
    try:
        config_all = load_server_config(project_path)
    except Exception as e:
        print_error(f"加载 server.json 失败: {e}")
        return

    protocol = "ftp" if "ftp" in config_all else "sftp" if "sftp" in config_all else None
    if not protocol:
        print_error("server.json 中未找到 'ftp' 或 'sftp' 配置")
        return
        
    config = config_all[protocol]
    print_server_info(protocol, config)
    
    print_step("正在分析同步计划，请稍候...")
    local_struct = get_local_structure(project_path, project_path, spec)
    remote_struct = {}
    
    try:
        if protocol == "ftp":
            with ftplib.FTP() as ftp:
                ftp.connect(config.get("host"), config.get("port", 21), timeout=config.get("timeout", 30))
                ftp.login(config.get("user"), config.get("password"))
                r_path = config.get("remote_path") or ftp.pwd()
                remote_struct = get_remote_structure_ftp(ftp, r_path, r_path)
        else:
            import paramiko
            transport = paramiko.Transport((config.get("host"), config.get("port", 22)))
            transport.connect(username=config.get("user"), password=config.get("password"))
            sftp = paramiko.SFTPClient.from_transport(transport)
            r_path = config.get("remote_path") or sftp.normalize('.')
            remote_struct = get_remote_structure_sftp(sftp, r_path, r_path)
            sftp.close()
            transport.close()
    except Exception as e:
        print_error(f"分析失败: {e}")
        if not ask_confirm("无法完整获取远程结构，是否直接开始强制同步?"):
            return

    sync_tree = generate_sync_tree(local_struct, remote_struct, project_path.name)
    console.print(sync_tree)
    
    if not ask_confirm("确认执行上述同步计划吗?"):
        print_warning("已取消同步操作。")
        return

    if protocol == "ftp":
        sync_ftp(project_path, config, spec)
    else:
        sync_sftp(project_path, config, spec)

def ensure_remote_dir_ftp(ftp, path):
    parts = path.strip("/").split("/")
    current = ""
    for part in parts:
        if not part: continue
        current += "/" + part
        try:
            ftp.cwd(current)
        except ftplib.error_perm:
            print_info(f"正在创建远程目录: {current}")
            try:
                ftp.mkd(current)
            except Exception as e:
                print_error(f"创建目录失败: {current}, 错误: {e}")

def upload_recursive_ftp(ftp, local_path, project_root, remote_root, spec):
    for item in local_path.iterdir():
        if is_ignored(item, project_root, spec, item.is_dir()):
            continue
        
        rel_path = item.relative_to(project_root)
        remote_file_path = (Path(remote_root) / rel_path).as_posix()
        
        if item.is_dir():
            try:
                ftp.mkd(remote_file_path)
            except ftplib.error_perm:
                pass 
            upload_recursive_ftp(ftp, item, project_root, remote_root, spec)
        else:
            print_info(f"正在上传: {rel_path}")
            try:
                with open(item, "rb") as f:
                    ftp.storbinary(f"STOR {remote_file_path}", f)
            except Exception as e:
                print_error(f"上传失败: {rel_path}, 错误: {e}")

def sync_ftp(project_path: Path, config: dict, spec: pathspec.PathSpec):
    print_info("使用 FTP 协议同步...")
    host = config.get("host")
    port = config.get("port", 21)
    user = config.get("user")
    password = config.get("password")
    remote_path = config.get("remote_path")
    timeout = config.get("timeout", 30)

    try:
        with ftplib.FTP() as ftp:
            ftp.connect(host, port, timeout=timeout)
            ftp.login(user, password)
            print_success(f"已连接到 FTP 服务器: {host}")
            
            if not remote_path:
                remote_path = ftp.pwd()
                print_info(f"未指定远程路径，自动获取当前目录: {remote_path}")
            
            ensure_remote_dir_ftp(ftp, remote_path)
            upload_recursive_ftp(ftp, project_path, project_path, remote_path, spec)
            
            print_step("正在清理远程多余文件...")
            cleanup_remote_ftp(ftp, project_path, remote_path, remote_path, spec)
            
            print_success("FTP 同步完成！")
    except Exception as e:
        print_error(f"FTP 同步过程中出错: {e}")

def cleanup_remote_ftp(ftp, local_root, current_remote, base_remote, spec):
    """递归清理远程多余文件"""
    try:
        try:
            items = ftp.nlst(current_remote)
        except ftplib.error_perm:
            return

        for remote_item_path in items:
            remote_item_path = remote_item_path.replace("\\", "/")
            name = Path(remote_item_path).name
            if name in (".", ".."): continue

            if not remote_item_path.startswith("/"):
                remote_item_path = (Path(current_remote) / name).as_posix()

            try:
                rel_path = Path(remote_item_path).relative_to(base_remote)
            except ValueError:
                rel_path = Path(remote_item_path.replace(base_remote, "", 1).lstrip("/"))
                
            local_item_path = local_root / rel_path

            is_dir = False
            try:
                # 依然尝试用 size 来判断文件/目录，减少 cwd 交互
                ftp.size(remote_item_path)
            except ftplib.error_perm:
                is_dir = True

            if is_dir:
                cleanup_remote_ftp(ftp, local_root, remote_item_path, base_remote, spec)
                if not local_item_path.exists() and not is_ignored(local_item_path, local_root, spec, True):
                    print_warning(f"正在删除远程目录: {rel_path}")
                    try:
                        ftp.rmd(remote_item_path)
                    except Exception as e:
                        print_error(f"删除目录失败: {rel_path}, {e}")
            else:
                if not local_item_path.exists() and not is_ignored(local_item_path, local_root, spec, False):
                    print_warning(f"正在删除远程文件: {rel_path}")
                    try:
                        ftp.delete(remote_item_path)
                    except Exception as e:
                        print_error(f"删除文件失败: {rel_path}, {e}")
    except Exception as e:
        print_error(f"清理远程文件时出错: {e}")

def ensure_remote_dir_sftp(sftp, path):
    parts = path.strip("/").split("/")
    current = ""
    for part in parts:
        if not part: continue
        current += "/" + part
        try:
            sftp.stat(current)
        except IOError:
            print_info(f"正在创建远程目录: {current}")
            try:
                sftp.mkdir(current)
            except Exception as e:
                print_error(f"创建目录失败: {current}, 错误: {e}")

def upload_recursive_sftp(sftp, local_path, project_root, remote_root, spec):
    for item in local_path.iterdir():
        if is_ignored(item, project_root, spec, item.is_dir()):
            continue
        
        rel_path = item.relative_to(project_root)
        remote_file_path = (Path(remote_root) / rel_path).as_posix()
        
        if item.is_dir():
            try:
                sftp.stat(remote_file_path)
            except IOError:
                sftp.mkdir(remote_file_path)
            upload_recursive_sftp(sftp, item, project_root, remote_root, spec)
        else:
            print_info(f"正在上传: {rel_path}")
            try:
                sftp.put(str(item), remote_file_path)
            except Exception as e:
                print_error(f"上传失败: {rel_path}, 错误: {e}")

def sync_sftp(project_path: Path, config: dict, spec: pathspec.PathSpec):
    try:
        import paramiko
    except ImportError:
        print_error("缺少 paramiko 库，请运行 'uv add paramiko' 以支持 SFTP。")
        return

    print_info("使用 SFTP 协议同步...")
    host = config.get("host")
    port = config.get("port", 22)
    user = config.get("user")
    password = config.get("password")
    remote_path = config.get("remote_path")
    
    try:
        transport = paramiko.Transport((host, port))
        transport.connect(username=user, password=password)
        sftp = paramiko.SFTPClient.from_transport(transport)
        print_success(f"已连接到 SFTP 服务器: {host}")
        
        if not remote_path:
            remote_path = sftp.normalize('.')
            print_info(f"未指定远程路径，自动获取当前目录: {remote_path}")
        
        ensure_remote_dir_sftp(sftp, remote_path)
        upload_recursive_sftp(sftp, project_path, project_path, remote_path, spec)
        
        print_step("正在清理远程多余文件...")
        cleanup_remote_sftp(sftp, project_path, remote_path, remote_path, spec)
        
        print_success("SFTP 同步完成！")
        sftp.close()
        transport.close()
    except Exception as e:
        print_error(f"SFTP 同步过程中出错: {e}")

def cleanup_remote_sftp(sftp, local_root, current_remote, base_remote, spec):
    """递归清理远程多余文件 (SFTP)"""
    try:
        items = sftp.listdir_attr(current_remote)
        for item in items:
            name = item.filename
            if name in (".", ".."): continue
            
            remote_item_path = (Path(current_remote) / name).as_posix()
            rel_path = Path(remote_item_path).relative_to(base_remote)
            local_item_path = local_root / rel_path
            
            is_dir = stat.S_ISDIR(item.st_mode)

            if is_dir:
                cleanup_remote_sftp(sftp, local_root, remote_item_path, base_remote, spec)
                if not local_item_path.exists() and not is_ignored(local_item_path, local_root, spec, True):
                    print_warning(f"正在删除远程目录: {rel_path}")
                    try:
                        sftp.rmdir(remote_item_path)
                    except Exception as e:
                        print_error(f"删除目录失败: {rel_path}, {e}")
            else:
                if not local_item_path.exists() and not is_ignored(local_item_path, local_root, spec, False):
                    print_warning(f"正在删除远程文件: {rel_path}")
                    try:
                        sftp.remove(remote_item_path)
                    except Exception as e:
                        print_error(f"删除文件失败: {rel_path}, {e}")
    except Exception as e:
        print_error(f"清理远程文件时出错: {e}")
