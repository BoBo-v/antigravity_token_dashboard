#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Antigravity Token 消耗统计看板 - 一键启动器
自动启动 FastAPI 服务并调用默认浏览器打开前端看板
"""

import os
import sys
import time
import webbrowser
import threading
from pathlib import Path

# 将项目目录加入 sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

try:
    import uvicorn
except ImportError:
    print("[!] 缺少 uvicorn 依赖，正在尝试安装: pip install uvicorn fastapi")
    os.system(f'"{sys.executable}" -m pip install uvicorn fastapi')
    import uvicorn


def kill_port_owner(port: int = 8765):
    """如果端口被残留的旧进程占用，自动结束它，保证最新代码生效"""
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


def open_browser(url: str):
    """延时 1 秒等待服务端口启动后自动唤起浏览器"""
    time.sleep(1.2)
    print(f"[*] 正在自动打开浏览器: {url}")
    webbrowser.open(url)


def main():
    host = "127.0.0.1"
    port = 8765
    url = f"http://{host}:{port}"

    kill_port_owner(port)

    print("=" * 80)
    print("   Antigravity (反重力) 本地 Token 消耗可视化大屏")
    print(f"   本地服务地址 : {url}")
    print("   按 Ctrl + C 可随时停止服务")
    print("=" * 80)

    # 启动后台线程打开浏览器
    threading.Thread(target=open_browser, args=(url,), daemon=True).start()

    # 启动 uvicorn
    uvicorn.run("backend.app:app", host=host, port=port, log_level="info", reload=False)


if __name__ == "__main__":
    main()
