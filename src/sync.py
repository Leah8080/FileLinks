import os
import json
import ftplib
from pathlib import Path
import pathspec
from src.ui import print_info, print_success, print_error, print_warning, print_step, print_server_info, ask_confirm, console
from src.filter import is_ignored

def generate_tree(path: Path, project_root: Path, spec, tree=None):
    """递归生成 Rich 目录树"""
    from rich.tree import Tree
    
    if tree is None:
        tree = Tree(f"[bold blue]📁 {path.name}[/bold blue]")
    
    # 排序：文件夹在前，文件在后
    items = sorted(list(path.iterdir()), key=lambda x: (not x.is_dir(), x.name.lower()))
    
    for item in items:
        if is_ignored(item, project_root, spec, item.is_dir()):
            continue
            
        if item.is_dir():
            branch = tree.add(f"[bold blue]📁 {item.name}[/bold blue]")
            generate_tree(item, project_root, spec, branch)
        else:
            tree.add(f"[green]📄 {item.name}[/green]")
    return tree

def count_local_items(path: Path, project_root: Path, spec):
    """统计待同步的文件和文件夹数量"""
    file_count = 0
    dir_count = 0
    for item in path.iterdir():
        if is_ignored(item, project_root, spec, item.is_dir()):
            continue
        if item.is_dir():
            dir_count += 1
            sub_files, sub_dirs = count_local_items(item, project_root, spec)
            file_count += sub_files
            dir_count += sub_dirs
        else:
            file_count += 1
    return file_count, dir_count

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

    # 1. 显示服务器信息
    print_server_info(protocol, config)
    
    # 2. 统计并显示本地待同步信息
    print_step("正在分析本地待同步文件...")
    file_count, dir_count = count_local_items(project_path, project_path, spec)
    print_info(f"待同步: [bold]{file_count}[/bold] 个文件, [bold]{dir_count}[/bold] 个文件夹")
    
    # 3. 显示目录树
    print_step("待同步目录结构:")
    tree = generate_tree(project_path, project_path, spec)
    console.print(tree)
    
    # 4. 用户确认
    if not ask_confirm("确认开始同步到服务器吗?"):
        print_warning("已取消同步操作。")
        return

    if protocol == "ftp":
        sync_ftp(project_path, config, spec)
    else:
        sync_sftp(project_path, config, spec)

def ensure_remote_dir_ftp(ftp, path):
    """确保远程 FTP 目录存在"""
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
    """递归上传文件到 FTP"""
    for item in local_path.iterdir():
        if is_ignored(item, project_root, spec, item.is_dir()):
            continue
        
        rel_path = item.relative_to(project_root)
        remote_file_path = (Path(remote_root) / rel_path).as_posix()
        
        if item.is_dir():
            try:
                ftp.mkd(remote_file_path)
            except ftplib.error_perm:
                pass # 目录可能已存在
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
            
            # 如果 remote_path 为空，获取当前工作目录
            if not remote_path:
                remote_path = ftp.pwd()
                print_info(f"未指定远程路径，自动获取当前目录: {remote_path}")
            
            # 确保远程根目录存在
            ensure_remote_dir_ftp(ftp, remote_path)
            
            # 开始递归同步
            upload_recursive_ftp(ftp, project_path, project_path, remote_path, spec)
            
            # 开始清理多余文件
            print_step("正在清理远程多余文件...")
            cleanup_remote_ftp(ftp, project_path, remote_path, spec)
            
            print_success("FTP 同步完成！")

def cleanup_remote_ftp(ftp, local_root, remote_root, spec):
    """递归删除远程服务器上多余的文件和目录"""
    try:
        items = ftp.nlst(remote_root)
    except ftplib.error_perm:
        return # 目录为空或不存在

    for remote_item_path in items:
        # 获取相对于远程根目录的路径
        try:
            rel_path = Path(remote_item_path).relative_to(remote_root)
        except ValueError:
            # 有些 FTP 返回的是绝对路径，有些是相对路径
            rel_path = Path(remote_item_path.replace(remote_root, "", 1).strip("/"))
            
        local_item_path = local_root / rel_path
        
        # 判断远程项是文件还是目录 (FTP 比较麻烦，尝试进入目录)
        is_dir = False
        try:
            ftp.cwd(remote_item_path)
            ftp.cwd("..") # 能够进入说明是目录
            is_dir = True
        except ftplib.error_perm:
            is_dir = False

        if is_dir:
            # 递归清理子目录
            cleanup_remote_ftp(ftp, local_root, remote_item_path, spec)
            # 如果本地不存在该目录且未被忽略，则删除
            if not local_item_path.exists() and not is_ignored(local_item_path, local_root, spec, True):
                print_warning(f"正在删除远程目录: {rel_path}")
                try:
                    ftp.rmd(remote_item_path)
                except Exception as e:
                    print_error(f"删除目录失败: {rel_path}, {e}")
        else:
            # 如果本地不存在该文件且未被忽略，则删除
            if not local_item_path.exists() and not is_ignored(local_item_path, local_root, spec, False):
                print_warning(f"正在删除远程文件: {rel_path}")
                try:
                    ftp.delete(remote_item_path)
                except Exception as e:
                    print_error(f"删除文件失败: {rel_path}, {e}")
            
    except Exception as e:
        print_error(f"FTP 同步过程中出错: {e}")

def ensure_remote_dir_sftp(sftp, path):
    """确保远程 SFTP 目录存在"""
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
    """递归上传文件到 SFTP"""
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
        print_error("缺少 paramiko 库，请运行 'pip install paramiko' 以支持 SFTP。")
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
        
        # 如果 remote_path 为空，获取当前工作目录
        if not remote_path:
            remote_path = sftp.normalize('.')
            print_info(f"未指定远程路径，自动获取当前目录: {remote_path}")
        
        # 确保远程根目录存在
        ensure_remote_dir_sftp(sftp, remote_path)
        
        # 开始递归同步
        upload_recursive_sftp(sftp, project_path, project_path, remote_path, spec)
        
        # 开始清理多余文件
        print_step("正在清理远程多余文件...")
        cleanup_remote_sftp(sftp, project_path, remote_path, spec)
        
        print_success("SFTP 同步完成！")
        
        sftp.close()
        transport.close()
    except Exception as e:
        print_error(f"SFTP 同步过程中出错: {e}")

def cleanup_remote_sftp(sftp, local_root, remote_root, spec):
    """递归删除远程 SFTP 服务器上多余的文件和目录"""
    import stat
    try:
        items = sftp.listdir_attr(remote_root)
    except IOError:
        return

    for item in items:
        remote_item_path = (Path(remote_root) / item.filename).as_posix()
        rel_path = Path(remote_item_path).relative_to(remote_root)
        local_item_path = local_root / rel_path
        
        is_dir = stat.S_ISDIR(item.st_mode)

        if is_dir:
            # 递归清理子目录
            cleanup_remote_sftp(sftp, local_root, remote_item_path, spec)
            # 如果本地不存在该目录且未被忽略，则删除
            if not local_item_path.exists() and not is_ignored(local_item_path, local_root, spec, True):
                print_warning(f"正在删除远程目录: {rel_path}")
                try:
                    sftp.rmdir(remote_item_path)
                except Exception as e:
                    print_error(f"删除目录失败: {rel_path}, {e}")
        else:
            # 如果本地不存在该文件且未被忽略，则删除
            if not local_item_path.exists() and not is_ignored(local_item_path, local_root, spec, False):
                print_warning(f"正在删除远程文件: {rel_path}")
                try:
                    sftp.remove(remote_item_path)
                except Exception as e:
                    print_error(f"删除文件失败: {rel_path}, {e}")
