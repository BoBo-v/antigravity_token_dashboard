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
    print("[*] 正在等待本地后端服务就绪...", end="", flush=True)
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(f"{url}/", timeout=0.8) as resp:
                if resp.status == 200:
                    print(" [就绪!]")
                    return True
        except Exception:
            time.sleep(0.2)
            print(".", end="", flush=True)
    print(" [超时!]")
    return False


def main():
    host = "127.0.0.1"
    port = 8765
    url = f"http://{host}:{port}"

    kill_port_owner(port)

    print("=" * 70)
    print("   正在启动 Antigravity Token 独立桌面客户端...")
    print(f"   后台服务绑定: {url}")
    print("=" * 70)

    # 1. 启动嵌入式 FastAPI 服务线程
    server_thread = ServerThread(host=host, port=port)
    server_thread.start()

    # 2. 严谨等待服务完全响应 200，杜绝早期请求失败导致黑屏
    if not wait_for_server(url, timeout=12.0):
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

    try:
        # debug=True 允许用户在窗口中右键“检查”调试工具，便于观察
        webview.start(gui="edgechromium", debug=True)
    except Exception as e:
        print(f"[!] WebView2 启动异常: {e}，尝试通用 GUI 启动...")
        try:
            webview.start(debug=True)
        except Exception as e2:
            print(f"[!] 原生窗口启动失败: {e2}，自动切换为默认浏览器打开...")
            import webbrowser
            webbrowser.open(url)
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass

    # 4. 窗口关闭后清理释放端口
    server_thread.stop()
    sys.exit(0)


if __name__ == "__main__":
    main()
