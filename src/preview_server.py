import http.server
import socketserver
import threading
import os
import time
from functools import partial
from pathlib import Path
from src.ui import print_success, print_info, print_error, print_warning

class SilentHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """静默的 HTTP 请求处理器，不在控制台输出每一个 GET 请求"""
    def log_message(self, format, *args):
        # 覆盖此方法以禁止日志输出到控制台
        pass

class PreviewServer:
    def __init__(self):
        self.server = None
        self.thread = None
        self.port = 8000
        self.project_path = None
        self.is_running = False

    def start(self, project_path: Path, port: int = 8000):
        """在后台线程启动服务器"""
        if self.is_running:
            if self.project_path == project_path:
                print_info(f"预览服务器已在运行: http://localhost:{self.port}")
                return True
            else:
                self.stop()

        self.project_path = project_path
        self.port = port
        
        # 使用事件来同步服务器是否成功启动
        startup_event = threading.Event()

        def run_server():
            # 寻找可用端口
            current_port = self.port
            while True:
                try:
                    # 使用 partial 传递 directory 参数给 handler (Python 3.7+)
                    handler_class = partial(SilentHTTPRequestHandler, directory=str(self.project_path))
                    
                    # 允许端口重用
                    socketserver.TCPServer.allow_reuse_address = True
                    with socketserver.TCPServer(("", current_port), handler_class) as httpd:
                        self.server = httpd
                        self.port = current_port
                        self.is_running = True
                        print_success(f"本地预览已开启: http://localhost:{current_port}")
                        startup_event.set()
                        httpd.serve_forever()
                        break
                except OSError as e:
                    if "address already in use" in str(e).lower() or e.errno == 98 or e.errno == 10048:
                        current_port += 1
                        if current_port > self.port + 10:
                            print_error(f"无法开启预览服务器：端口 {self.port}-{self.port+10} 均被占用。")
                            self.is_running = False
                            startup_event.set()
                            break
                    else:
                        print_error(f"预览服务器启动失败: {e}")
                        self.is_running = False
                        startup_event.set()
                        break
                except Exception as e:
                    print_error(f"预览服务器运行出错: {e}")
                    self.is_running = False
                    startup_event.set()
                    break

        self.thread = threading.Thread(target=run_server, daemon=True)
        self.thread.start()
        
        # 等待服务器启动结果
        startup_event.wait(timeout=2.0)
        return self.is_running

    def stop(self):
        """停止服务器"""
        if self.server:
            try:
                # 必须在另一个线程或之前调用 shutdown
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                print_info("正在关闭本地预览服务器...")
            except Exception as e:
                print_error(f"关闭预览服务器时出错: {e}")
        self.is_running = False
        self.server = None
        self.thread = None

# 创建全局单例
preview_manager = PreviewServer()
