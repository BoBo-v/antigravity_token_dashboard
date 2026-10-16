#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Antigravity Token 消耗统计看板 - Windows 原生独立桌面应用
基于 pywebview (调用 Windows 10/11 内置 Edge WebView2 内核)
提供独立软件窗口、独立任务栏图标与干净的生命周期管理
"""

import sys
import time
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
    """如果端口被残留的旧进程占用，自动结束它，保证最新代码生效"""
    import os
    import subprocess
    try:
        cmd = f'powershell -Command "Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique"'
        out = subprocess.check_output(cmd, shell=True).decode('utf-8', errors='ignore').strip()
        if out:
            pids = [int(p) for p in out.split() if p.isdigit()]
            for pid in pids:
                if pid != os.getpid() and pid > 0:
                    print(f"[*] 发现旧服务进程 (PID {pid}) 占用端口 {port}，正在清理释放...")
                    subprocess.call(f"taskkill /F /PID {pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(0.5)
    except Exception:
        pass


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

    # 稍等 0.6 秒让端口监听就绪
    time.sleep(0.6)

    # 2. 创建原生独立窗口（使用 Windows 10/11 内置 WebView2 渲染器）
    window = webview.create_window(
        title="Antigravity Token 消耗统计看板",
        url=url,
        width=1024,
        height=680,
        min_size=(480, 360),
        text_select=True,
    )

    try:
        webview.start(gui="edgechromium")
    except Exception:
        webview.start()

    # 3. 窗口关闭后清理释放端口
    server_thread.stop()
    sys.exit(0)


if __name__ == "__main__":
    main()
