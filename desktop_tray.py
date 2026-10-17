#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Antigravity Token Dashboard - Windows 系统原生托盘管理器
提供：
1. 关闭窗口自动最小化到托盘（Hide 代替 Close）
2. 托盘悬浮 Tooltip 动态展示 5H 消耗与释放预测（如 ⚡ 5H已用: 12.5M (92%) | ⏳ 42分后释放 1.8M）
3. 托盘右键菜单：打开看板、一键刷新、开机自启动切换、彻底退出
4. 点击/双击托盘图标唤醒并前置窗口
"""

import os
import sys
import time
import threading
import winreg
from pathlib import Path

REG_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_APP_NAME = "AntigravityTokenDashboard"


def is_autostart_enabled() -> bool:
    """检查是否已开启开机自启"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_KEY, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, REG_APP_NAME)
            return bool(val)
    except Exception:
        return False


def set_autostart(enabled: bool) -> bool:
    """设置或取消开机自启"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                if getattr(sys, "frozen", False):
                    cmd = f'"{sys.executable}" --tray'
                else:
                    curr_dir = Path(__file__).resolve().parent
                    cmd = f'pythonw.exe "{curr_dir / "desktop.py"}" --tray'
                winreg.SetValueEx(key, REG_APP_NAME, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, REG_APP_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception as e:
        print(f"Failed to set autostart: {e}")
        return False


class DesktopTrayManager:
    def __init__(self, window):
        self.window = window
        self.form = None
        self.notify_icon = None
        self.force_exit = False
        self.first_minimize = True
        self._running = True
        self._updater_thread = None

    def setup(self):
        """挂载 pywebview 事件监听"""
        if sys.platform != "win32":
            return

        self.window.events.shown += self._on_window_shown
        self.window.events.closing += self._on_window_closing

    def _on_window_shown(self):
        """窗口加载呈现后，获取底层 WinForms Form 并初始化托盘"""
        try:
            import webview.platforms.winforms as wf
            self.form = wf.BrowserView.instances.get(self.window.uid)
            if self.form:
                import clr
                clr.AddReference("System.Windows.Forms")
                import System.Windows.Forms as WinForms
                self.form.Invoke(WinForms.MethodInvoker(self._init_tray_ui))
        except Exception as e:
            print(f"[!] 初始化系统托盘异常: {e}")

    def _create_app_icon(self):
        """生成原生高品质托盘图标"""
        try:
            import clr
            clr.AddReference("System.Drawing")
            import System.Drawing as Drawing

            # 优先使用窗体原有图标
            if self.form and self.form.Icon:
                return self.form.Icon

            # 绘制现代质感圆形图标（紫蓝渐变底色 + 白色 A 标）
            bmp = Drawing.Bitmap(32, 32)
            g = Drawing.Graphics.FromImage(bmp)
            g.SmoothingMode = Drawing.Drawing2D.SmoothingMode.AntiAlias

            brush = Drawing.SolidBrush(Drawing.Color.FromArgb(99, 102, 241))  # Indigo 600
            g.FillEllipse(brush, 2, 2, 28, 28)

            font = Drawing.Font("Arial", 14, Drawing.FontStyle.Bold)
            text_brush = Drawing.SolidBrush(Drawing.Color.White)
            g.DrawString("A", font, text_brush, 7, 5)

            g.Dispose()
            h_icon = bmp.GetHicon()
            return Drawing.Icon.FromHandle(h_icon)
        except Exception:
            import System.Drawing as Drawing
            return Drawing.SystemIcons.Application

    def _init_tray_ui(self):
        """在 WinForms UI 线程中构建 NotifyIcon 与右键上下文菜单"""
        import clr
        clr.AddReference("System.Windows.Forms")
        clr.AddReference("System.Drawing")
        import System.Windows.Forms as WinForms
        import System.Drawing as Drawing

        self.notify_icon = WinForms.NotifyIcon()
        self.notify_icon.Icon = self._create_app_icon()
        self.notify_icon.Text = self.get_metrics_text()

        # 构建上下文菜单
        cms = WinForms.ContextMenuStrip()

        # 1. 打开看板 (加粗主菜单项)
        open_item = WinForms.ToolStripMenuItem("📈 打开看板")
        open_item.Font = Drawing.Font(open_item.Font, Drawing.FontStyle.Bold)
        open_item.Click += lambda s, e: self.restore_window()
        cms.Items.Add(open_item)

        # 2. 一键刷新
        refresh_item = WinForms.ToolStripMenuItem("🔄 立即刷新数据")
        refresh_item.Click += lambda s, e: self.manual_refresh()
        cms.Items.Add(refresh_item)

        # 分割线
        cms.Items.Add(WinForms.ToolStripSeparator())

        # 3. 开机自启切换
        autostart_item = WinForms.ToolStripMenuItem("🚀 开机自动启动")
        autostart_item.Checked = is_autostart_enabled()
        autostart_item.Click += lambda s, e: self.toggle_autostart(autostart_item)
        cms.Items.Add(autostart_item)

        # 分割线
        cms.Items.Add(WinForms.ToolStripSeparator())

        # 4. 彻底退出
        exit_item = WinForms.ToolStripMenuItem("❌ 彻底退出")
        exit_item.Click += lambda s, e: self.exit_app()
        cms.Items.Add(exit_item)

        self.notify_icon.ContextMenuStrip = cms

        # 单击与双击左键唤醒
        self.notify_icon.MouseClick += self._on_tray_mouse_click
        self.notify_icon.DoubleClick += lambda s, e: self.restore_window()

        self.notify_icon.Visible = True

        # 如果是开机静默常驻启动（带 --tray 或 --minimized），启动时直接隐藏至托盘
        # 否则（常规双击启动），确保强制前置激活呈现主窗口，杜绝被操作系统误隐藏
        if "--tray" in sys.argv or "--minimized" in sys.argv:
            if self.form:
                try:
                    self.form.Hide()
                except Exception:
                    pass
        else:
            if self.form:
                try:
                    self.form.Show()
                    self.form.WindowState = WinForms.FormWindowState.Normal
                    self.form.Activate()
                    self.form.BringToFront()
                except Exception:
                    pass

        # 启动后台定时器刷新 Tooltip（每 20 秒更新一次）
        self._updater_thread = threading.Thread(target=self._periodic_tooltip_updater, daemon=True)
        self._updater_thread.start()

    def _on_tray_mouse_click(self, sender, args):
        import System.Windows.Forms as WinForms
        if args.Button == WinForms.MouseButtons.Left:
            self.restore_window()

    def get_metrics_text(self) -> str:
        """从后端实时计算 5H 滑动窗口指标，格式化为限制 63 字符内的精确 Tooltip"""
        try:
            from backend.scanner import scanner_service
            from backend.app import load_quota_config

            all_turns = scanner_service.get_all_turns()
            quotas = scanner_service.calculate_quotas(all_turns)
            cfg = load_quota_config()

            q5h = quotas.get("quota_5h", {})
            used_tokens = q5h.get("used_tokens", 0)
            used_m = used_tokens / 1_000_000

            pct = cfg.get("quota_5h", {}).get("remaining_pct")
            relief_sec = q5h.get("next_relief_seconds", 0)
            relief_tokens = q5h.get("next_relief_tokens", 0)
            relief_m = relief_tokens / 1_000_000

            if relief_sec > 0:
                m = max(1, relief_sec // 60)
                if pct is not None:
                    text = f"⚡ 5H已用:{used_m:.1f}M({pct}%) | ⏳ {m}分后释放{relief_m:.1f}M"
                else:
                    text = f"⚡ 5H已用:{used_m:.1f}M | ⏳ {m}分后释放{relief_m:.1f}M"
            else:
                if pct is not None:
                    text = f"⚡ 5H已用:{used_m:.1f}M({pct}%) | 额度充足"
                else:
                    text = f"⚡ 5H已用:{used_m:.1f}M | 额度充足"

            # Windows NotifyIcon.Text 严格上限 63 字符
            return text[:63]
        except Exception:
            return "Antigravity Token 消耗统计看板"[:63]

    def update_tooltip(self):
        """刷新托盘悬浮提示文案"""
        if self.notify_icon:
            try:
                new_text = self.get_metrics_text()
                self.notify_icon.Text = new_text
            except Exception:
                pass

    def _periodic_tooltip_updater(self):
        """后台轮询更新托盘提示文案"""
        while self._running:
            time.sleep(20)
            if self._running:
                self.update_tooltip()

    def restore_window(self):
        """显示并激活主窗口"""
        if self.form:
            import clr
            clr.AddReference("System.Windows.Forms")
            import System.Windows.Forms as WinForms
            self.form.Invoke(WinForms.MethodInvoker(self._do_restore))

    def _do_restore(self):
        import System.Windows.Forms as WinForms
        self.form.Show()
        if self.form.WindowState == WinForms.FormWindowState.Minimized:
            self.form.WindowState = WinForms.FormWindowState.Normal
        self.form.Activate()
        self.form.BringToFront()

    def _on_window_closing(self):
        """拦截窗口关闭按钮，实现最小化到托盘"""
        if not self.force_exit:
            if self.form:
                import clr
                clr.AddReference("System.Windows.Forms")
                import System.Windows.Forms as WinForms

                self.form.Invoke(WinForms.MethodInvoker(lambda: self.form.Hide()))

                # 首次最小化时弹出 Windows 原生气泡提醒
                if self.first_minimize:
                    self.first_minimize = False
                    try:
                        self.notify_icon.ShowBalloonTip(
                            3000,
                            "已最小化到系统托盘",
                            "看板已转入后台监控。双击托盘图标可重新打开，右键可进行设置或退出。",
                            WinForms.ToolTipIcon.Info
                        )
                    except Exception:
                        pass
            return False  # 返回 False 阻止 pywebview 销毁窗口
        return True  # 允许销毁

    def manual_refresh(self):
        """右键菜单一键刷新"""
        def run_refresh():
            try:
                from backend.scanner import scanner_service
                import System.Windows.Forms as WinForms

                scanner_service.scan(force=True)
                self.update_tooltip()
                if self.notify_icon:
                    self.notify_icon.ShowBalloonTip(
                        2000,
                        "数据已刷新",
                        f"已重新扫描 {scanner_service.total_db_count} 个数据库，当前指标已更新。",
                        WinForms.ToolTipIcon.Info
                    )
            except Exception:
                pass

        threading.Thread(target=run_refresh, daemon=True).start()

    def toggle_autostart(self, item):
        """切换开机自启动"""
        import System.Windows.Forms as WinForms
        new_state = not item.Checked
        if set_autostart(new_state):
            item.Checked = new_state
            msg = "开机自启已开启" if new_state else "开机自启已关闭"
            if self.notify_icon:
                self.notify_icon.ShowBalloonTip(2000, "设置变更", msg, WinForms.ToolTipIcon.Info)

    def exit_app(self):
        """右键菜单彻底退出"""
        self.force_exit = True
        self._running = False
        if self.notify_icon:
            try:
                self.notify_icon.Visible = False
                self.notify_icon.Dispose()
            except Exception:
                pass
        if self.form:
            import clr
            clr.AddReference("System.Windows.Forms")
            import System.Windows.Forms as WinForms
            self.form.Invoke(WinForms.MethodInvoker(lambda: self.form.Close()))

    def dispose(self):
        """资源释放"""
        self._running = False
        if self.notify_icon:
            try:
                self.notify_icon.Visible = False
                self.notify_icon.Dispose()
            except Exception:
                pass
