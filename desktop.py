#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Antigravity Token 消耗统计看板 - Windows 原生独立桌面应用
基于 pywebview (调用 Windows 10/11 内置 Edge WebView2 内核)
提供独立软件窗口、独立任务栏图标与干净的生命周期管理
"""

import sys
import time
import os
import threading
from pathlib import Path

# 防止在使用 pythonw 无控制台运行时 sys.stdout / sys.stderr 为 None 导致 print 报错
if sys.stdout is None:
    import io
    sys.stdout = io.StringIO()
if sys.stderr is None:
    import io
    sys.stderr = io.StringIO()


def hide_console_window():
    """在 Windows 系统下自动隐藏控制台黑框窗口"""
    if sys.platform == "win32":
        try:
            import ctypes
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 0)  # 0 = SW_HIDE
        except Exception:
            pass


# 针对控制台启动，在加载任何重型依赖（uvicorn/fastapi）前立即毫秒级隐藏黑框
if sys.platform == "win32" and "--show-console" not in sys.argv and "--debug" not in sys.argv:
    hide_console_window()


BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

try:
    import webview
except ImportError:
    print("[!] 正在安装 pywebview 桌面支持库...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pywebview"])
    import webview

import uvicorn
from backend.app import app


class ServerThread(threading.Thread):
    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.server = None

    def run(self):
        config = uvicorn.Config(
            app=app,
            host=self.host,
            port=self.port,
            log_level="warning"
        )
        self.server = uvicorn.Server(config)
        self.server.run()

    def stop(self):
        if self.server:
            self.server.should_exit = True


def kill_port_owner(port: int = 8765):
    """如果端口被残留的旧进程占用，毫秒级清理释放"""
    import subprocess
    try:
        cmd = 'netstat -ano -p tcp'
        out = subprocess.check_output(cmd, shell=True).decode('utf-8', errors='ignore')
        current_pid = os.getpid()
        killed_any = False
        for line in out.splitlines():
            line = line.strip()
            if f":{port}" in line and "LISTENING" in line:
                parts = line.split()
                if len(parts) >= 5:
                    pid_str = parts[-1]
                    if pid_str.isdigit():
                        pid = int(pid_str)
                        if pid != current_pid and pid > 0:
                            print(f"[*] 发现旧服务进程 (PID {pid}) 占用端口 {port}，正在清理释放...")
                            subprocess.call(f"taskkill /F /PID {pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            killed_any = True
        if killed_any:
            time.sleep(0.3)
    except Exception:
        pass


def wait_for_server(url: str, timeout: float = 15.0) -> bool:
    """轮询等待本地 FastAPI 服务完全就绪，杜绝在服务未就绪时加载导致黑屏/连接拒绝"""
    import urllib.request
    start = time.time()
    show_log = "--show-console" in sys.argv or "--debug" in sys.argv
    if show_log:
        print("[*] 正在等待本地后端服务就绪...", end="", flush=True)
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(f"{url}/", timeout=0.8) as resp:
                if resp.status == 200:
                    if show_log:
                        print(" [就绪!]")
                    return True
        except Exception:
            time.sleep(0.2)
            if show_log:
                print(".", end="", flush=True)
    if show_log:
        print(" [超时!]")
    return False


def main():
    host = "127.0.0.1"
    port = 8765
    url = f"http://{host}:{port}"

    # 判断是否为调试模式或显式保留控制台
    debug_mode = "--debug" in sys.argv
    show_console = "--show-console" in sys.argv

    # 默认自动隐藏控制台黑框，给用户最纯粹的原生桌面客户端体验
    if not show_console and not debug_mode:
        hide_console_window()
        # 静默 pywebview 的内部调试日志
        import logging
        logging.getLogger("pywebview").setLevel(logging.ERROR)
        os.environ["PYWEBVIEW_LOG"] = "error"

    kill_port_owner(port)

    if show_console or debug_mode:
        print("=" * 70)
        print("   正在启动 Antigravity Token 独立桌面客户端...")
        print(f"   后台服务绑定: {url}")
        print("=" * 70)

    # 1. 启动嵌入式 FastAPI 服务线程
    server_thread = ServerThread(host=host, port=port)
    server_thread.start()

    # 2. 严谨等待服务完全响应 200，杜绝早期请求失败导致黑屏
    if not wait_for_server(url, timeout=12.0):
        if show_console or debug_mode:
            print("[!] 警告: 本地服务响应较慢，继续尝试打开窗口...")

    # 3. 创建原生独立窗口（使用 Windows 10/11 内置 WebView2 渲染器）
    window = webview.create_window(
        title="Antigravity Token 消耗统计看板",
        url=url,
        width=1024,
        height=680,
        min_size=(480, 360),
        text_select=True,
        background_color="#0b1120",
    )

    # 4. 初始化 Windows 系统托盘（关闭窗口最小化到托盘、悬浮指标提示、右键菜单与开机自启）
    tray_manager = None
    if sys.platform == "win32":
        try:
            from desktop_tray import DesktopTrayManager
            tray_manager = DesktopTrayManager(window)
            tray_manager.setup()
        except Exception as e:
            if show_console or debug_mode:
                print(f"[!] 系统托盘初始化失败（降级运行）: {e}")

    try:
        # 默认关闭 debug 避免控制台输出大量事件日志与检查弹框
        webview.start(gui="edgechromium", debug=debug_mode)
    except Exception as e:
        if show_console or debug_mode:
            print(f"[!] WebView2 启动异常: {e}，尝试通用 GUI 启动...")
        try:
            webview.start(debug=debug_mode)
        except Exception as e2:
            if show_console or debug_mode:
                print(f"[!] 原生窗口启动失败: {e2}，自动切换为默认浏览器打开...")
            import webbrowser
            webbrowser.open(url)
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
    finally:
        if tray_manager:
            tray_manager.dispose()

    # 5. 窗口关闭后清理释放端口
    server_thread.stop()
    sys.exit(0)


if __name__ == "__main__":
    main()
