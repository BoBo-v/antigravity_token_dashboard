#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Antigravity Token Dashboard - 全面标准自动化测试集
涵盖：静态资源校验、前端变量作用域完整性、FastAPI 后端接口契约、SQLite 解析聚合引擎、启动器脚本编码规范。
"""

import os
import sys
import json
import re
import unittest
from pathlib import Path

# 将项目根目录加入 sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from fastapi.testclient import TestClient
from backend.app import app
from backend.scanner import scanner_service, TokenScannerService
from backend.parser import MODEL_PLACEHOLDER_MAP


class TestStaticAssets(unittest.TestCase):
    """1. 静态资源与内置依赖离线完整性测试"""

    def setUp(self):
        self.static_dir = BASE_DIR / "static"
        self.client = TestClient(app)

    def test_index_html_exists_and_valid(self):
        index_file = self.static_dir / "index.html"
        self.assertTrue(index_file.exists(), "static/index.html 不存在")
        content = index_file.read_text(encoding="utf-8")
        self.assertGreater(len(content), 1000, "static/index.html 内容异常过短")
        self.assertIn('<div id="app">', content, "index.html 缺少 Vue 挂载容器")
        self.assertIn("createApp", content, "index.html 缺少 Vue 初始化代码")

    def test_vendor_libs_exist(self):
        libs_dir = self.static_dir / "libs"
        required_libs = [
            "vue.global.prod.js",
            "element-plus.js",
            "element-plus.css",
            "echarts.min.js",
            "icons-vue.js"
        ]
        for lib in required_libs:
            target = libs_dir / lib
            self.assertTrue(target.exists(), f"关键前端依赖缺失: libs/{lib}")
            self.assertGreater(target.stat().st_size, 1024, f"前端依赖文件大小异常: libs/{lib}")

    def test_static_routes_serve(self):
        res = self.client.get("/static/libs/vue.global.prod.js")
        self.assertEqual(res.status_code, 200)
        self.assertIn("javascript", res.headers.get("content-type", "").lower())


class TestFrontendIntegrity(unittest.TestCase):
    """2. 前端 JS 响应式作用域与模板变量完整性测试（杜绝 ReferenceError）"""

    def setUp(self):
        self.html = (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")
        scripts = re.findall(r'<script(?:\s+[^>]*)?>([\s\S]*?)<\/script>', self.html, re.IGNORECASE)
        self.main_script = [s for s in scripts if len(s) > 1000][0]

    def test_all_dot_value_variables_are_declared(self):
        """确保所有使用 .value 的响应式变量均已被 const/let/var 声明"""
        value_vars = set(re.findall(r'([a-zA-Z0-9_$]+)\.value\b', self.main_script))
        self.assertGreater(len(value_vars), 10, "未检测到足够的 ref 变量")

        undeclared = []
        for v in sorted(value_vars):
            pattern = rf'\b(const|let|var)\s+[^;]*?\b{v}\b'
            if not re.search(pattern, self.main_script):
                undeclared.append(v)

        self.assertEqual(undeclared, [], f"发现未声明的 .value 响应式变量: {undeclared}")

    def test_setup_return_variables_are_declared(self):
        """确保 setup() 返回的对象中所有键名在当前作用域均有定义"""
        idx = self.html.rfind('return {')
        end_idx = self.html.find('};', idx)
        ret_text = self.html[idx:end_idx]
        items = [
            line.strip().rstrip(',')
            for line in ret_text.splitlines()
            if line.strip() and not line.strip().startswith('return') and not line.strip().startswith('//')
        ]
        self.assertGreater(len(items), 30, "setup() 返回值属性过少")

        undeclared = []
        for item in items:
            name = item.split(':')[0].strip()
            pattern = rf'\b(const|let|var|function)\s+[^;{{]*?\b{name}\b'
            if not re.search(pattern, self.main_script):
                undeclared.append(name)

        self.assertEqual(undeclared, [], f"setup() 返回了未声明的作用域变量: {undeclared}")


class TestBackendAPI(unittest.TestCase):
    """3. 后端 FastAPI RESTful 接口契约测试"""

    def setUp(self):
        self.client = TestClient(app)

    def test_serve_index(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/html", res.headers.get("content-type", ""))
        self.assertIn("<title>Antigravity", res.text)

    def test_api_overview_contract(self):
        res = self.client.get("/api/overview")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("success"))
        self.assertIn("meta", data)
        self.assertIn("summary", data)
        self.assertIn("trend", data)
        self.assertIn("models", data)
        self.assertIn("quotas", data)
        self.assertIn("custom_quota", data)

        # 检查配额契约
        quotas = data["quotas"]
        self.assertIn("quota_5h", quotas)
        self.assertIn("quota_week", quotas)
        self.assertIn("weekly_reset_seconds", quotas["quota_week"])
        self.assertIn("next_relief_seconds", quotas["quota_5h"])

    def test_api_overview_time_ranges(self):
        for r in ["today", "yesterday", "week", "month", "all"]:
            res = self.client.get(f"/api/overview?range={r}")
            self.assertEqual(res.status_code, 200, f"时间范围 {r} 请求失败")
            data = res.json()
            self.assertTrue(data.get("success"))
            self.assertEqual(data.get("range"), r)
            self.assertIsInstance(data.get("trend"), list)

    def test_api_sessions_pagination(self):
        res = self.client.get("/api/sessions?page=1&page_size=5")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("success"))
        table_data = data.get("data", {})
        self.assertIn("items", table_data)
        self.assertIn("total", table_data)
        self.assertIn("page", table_data)
        self.assertIn("page_size", table_data)
        self.assertEqual(table_data["page"], 1)

    def test_api_quota_config_lifecycle(self):
        # 1. 读取当前配置
        get_res = self.client.get("/api/quota-config")
        self.assertEqual(get_res.status_code, 200)
        orig = get_res.json()
        self.assertTrue(orig.get("success"))

        # 2. 模拟前端保存校准
        payload = {
            "quota_5h": {"remaining_pct": 92, "reset_seconds": 12000, "reset_time_str": "3小时20分"},
            "quota_week": {"remaining_pct": 85, "reset_seconds": 500000, "reset_time_str": "5天18小时"}
        }
        post_res = self.client.post("/api/quota-config", json=payload)
        self.assertEqual(post_res.status_code, 200)
        saved = post_res.json()
        self.assertTrue(saved.get("success"))
        self.assertEqual(saved["data"]["quota_5h"]["remaining_pct"], 92)

    def test_api_refresh(self):
        res = self.client.post("/api/refresh")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("success"))
        self.assertIn("cost_ms", data)
        self.assertIn("刷新成功", data.get("message", ""))

    def test_api_export_csv(self):
        res = self.client.get("/api/export-csv?range=today")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/csv", res.headers.get("content-type", ""))
        self.assertTrue(res.content.startswith(b"\xef\xbb\xbf"), "导出的 CSV 缺少 UTF-8 BOM 头，可能在 Excel 中乱码")
        text = res.content.decode("utf-8")
        self.assertIn("session_id", text)
        self.assertIn("total_tokens", text)

    def test_api_no_cache_headers(self):
        """确保接口包含 no-cache 响应头，防止 WebView2/浏览器缓存导致定时刷新不更新"""
        for endpoint in ["/api/overview", "/api/sessions"]:
            res = self.client.get(endpoint)
            self.assertEqual(res.status_code, 200)
            cc = res.headers.get("Cache-Control", "")
            self.assertIn("no-cache", cc)
            self.assertIn("no-store", cc)

    def test_api_multi_source_filtering(self):
        """测试按工具来源 (all, antigravity, codex, claude-code) 进行过滤的接口契约"""
        for src in ["all", "antigravity", "codex", "claude-code"]:
            res = self.client.get(f"/api/overview?range=all&source={src}")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertTrue(data.get("success"))
            self.assertEqual(data.get("source"), src)
            self.assertIn("by_source", data.get("summary", {}))

            # 会话列表来源过滤测试
            s_res = self.client.get(f"/api/sessions?range=all&source={src}&page=1&page_size=5")
            self.assertEqual(s_res.status_code, 200)
            s_data = s_res.json()
            self.assertTrue(s_data.get("success"))
            if src != "all":
                for item in s_data["data"]["items"]:
                    self.assertEqual(item["source_app"], src)



class TestScannerEngine(unittest.TestCase):
    """4. SQLite 解析与聚合计算核心业务逻辑测试"""

    def setUp(self):
        self.scanner = TokenScannerService()
        self.mock_turns = [
            {
                "session_id": "mock-session-1",
                "turn_index": 1,
                "model": "claude-3-7-sonnet",
                "timestamp_sec": 1700000000,
                "input_tokens": 1000,
                "cache_read_tokens": 500,
                "cache_write_tokens": 0,
                "response_tokens": 300,
                "thinking_tokens": 200,
                "total_tokens": 2000,
                "total_output_tokens": 500,
                "duration_sec": 2.5,
                "speed_tps": 200.0,
                "ttft_sec": 0.5,
                "conversation_title": "测试会话1",
                "workspace": "D:/workspace",
                "hour_num": 10,
                "date_str": "2026-10-17"
            },
            {
                "session_id": "mock-session-1",
                "turn_index": 2,
                "model": "gemini-2.5-pro",
                "timestamp_sec": 1700000050,
                "input_tokens": 2000,
                "cache_read_tokens": 1500,
                "cache_write_tokens": 0,
                "response_tokens": 800,
                "thinking_tokens": 0,
                "total_tokens": 4300,
                "total_output_tokens": 800,
                "duration_sec": 4.0,
                "speed_tps": 200.0,
                "ttft_sec": 0.8,
                "conversation_title": "测试会话1",
                "workspace": "D:/workspace",
                "hour_num": 10,
                "date_str": "2026-10-17"
            }
        ]

    def test_calculate_summary(self):
        summary = self.scanner.calculate_summary(self.mock_turns)
        self.assertEqual(summary["total_tokens"], 6300)
        self.assertEqual(summary["input_tokens"], 3000)
        self.assertEqual(summary["cache_read_tokens"], 2000)
        self.assertEqual(summary["response_tokens"], 1100)
        self.assertEqual(summary["thinking_tokens"], 200)
        self.assertEqual(summary["turns_count"], 2)
        self.assertEqual(summary["sessions_count"], 1)
        self.assertIn("costs", summary)
        self.assertGreater(summary["costs"]["standard"]["total_usd"], 0)

    def test_calculate_models(self):
        models = self.scanner.calculate_models(self.mock_turns)
        self.assertEqual(len(models), 2)
        model_names = [m["model"] for m in models]
        self.assertIn("claude-3-7-sonnet", model_names)
        self.assertIn("gemini-2.5-pro", model_names)

    def test_model_placeholder_mapping(self):
        self.assertIsInstance(MODEL_PLACEHOLDER_MAP, dict)
        self.assertGreater(len(MODEL_PLACEHOLDER_MAP), 0)
        # 至少包含已知的占位符映射
        first_key = list(MODEL_PLACEHOLDER_MAP.keys())[0]
        self.assertTrue(first_key.startswith("MODEL_PLACEHOLDER_"))

    def test_auto_incremental_rescan(self):
        """测试超过缓存时限时自动触发轻量扫描并更新 last_scan_time"""
        # 初次调用
        self.scanner.get_all_turns()
        first_scan_ts = self.scanner._last_scan_ts
        self.assertGreater(first_scan_ts, 0)

        # 模拟缓存过期 (max_cache_age = 0.001 秒)
        import time
        time.sleep(0.01)
        self.scanner.get_all_turns(max_cache_age=0.005)
        second_scan_ts = self.scanner._last_scan_ts
        self.assertGreater(second_scan_ts, first_scan_ts, "缓存过期后未自动触发增量扫描更新时间戳")

    def test_claude_parser_mock(self):
        """测试 Claude Code 会话 JSONL 解析与 Token 提取"""
        import tempfile
        import json
        from backend.claude_parser import read_claude_session

        with tempfile.NamedTemporaryFile("w+", suffix=".jsonl", delete=False, encoding="utf-8") as f:
            f.write(json.dumps({"type": "user", "message": {"content": "测试用户提问"}}) + "\n")
            f.write(json.dumps({
                "type": "assistant",
                "timestamp": "2026-10-17T12:00:00.000Z",
                "message": {
                    "id": "msg-123",
                    "model": "claude-3-7-sonnet",
                    "usage": {
                        "input_tokens": 500,
                        "cache_read_input_tokens": 1200,
                        "cache_creation_input_tokens": 0,
                        "output_tokens": 300
                    }
                }
            }) + "\n")
            tmp_path = Path(f.name)

        try:
            records = read_claude_session(tmp_path)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["model"], "claude-3-7-sonnet")
            self.assertEqual(records[0]["input_tokens"], 500)
            self.assertEqual(records[0]["cache_read_tokens"], 1200)
            self.assertEqual(records[0]["response_tokens"], 300)
            self.assertEqual(records[0]["total_tokens"], 2000)
            self.assertEqual(records[0]["source_app"], "claude-code")
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def test_codex_parser_mock(self):
        """测试 OpenAI Codex 会话 .jsonl.zst 解码与递增 Token 提取"""
        import tempfile
        import json
        try:
            import zstandard as zstd
        except ImportError:
            return
        from backend.codex_parser import read_codex_session

        lines = [
            json.dumps({"type": "session_meta", "payload": {"session_id": "codex-test-sid-123"}}),
            json.dumps({"type": "turn_context", "payload": {"model": "gpt-5.5"}}),
            json.dumps({"type": "response_item", "payload": {"role": "user", "content": [{"text": "Codex 测试任务"}]}}),
            json.dumps({
                "type": "event_msg",
                "timestamp": "2026-10-17T12:00:00.000Z",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "total_token_usage": {"input_tokens": 1000, "cached_input_tokens": 800, "cache_write_input_tokens": 0, "output_tokens": 150, "reasoning_output_tokens": 50, "total_tokens": 1150},
                        "last_token_usage": {"input_tokens": 1000, "cached_input_tokens": 800, "cache_write_input_tokens": 0, "output_tokens": 150, "reasoning_output_tokens": 50, "total_tokens": 1150}
                    }
                }
            })
        ]
        content_bytes = "\n".join(lines).encode("utf-8")
        cctx = zstd.ZstdCompressor()
        compressed = cctx.compress(content_bytes)

        with tempfile.NamedTemporaryFile("wb", suffix=".jsonl.zst", delete=False) as f:
            f.write(compressed)
            tmp_path = Path(f.name)

        try:
            records = read_codex_session(tmp_path)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["session_id"], "codex-test-sid-123")
            self.assertEqual(records[0]["model"], "gpt-5.5")
            self.assertEqual(records[0]["input_tokens"], 1000)
            self.assertEqual(records[0]["cache_read_tokens"], 800)
            self.assertEqual(records[0]["thinking_tokens"], 50)
            self.assertEqual(records[0]["total_tokens"], 1150)
            self.assertEqual(records[0]["source_app"], "codex")
        finally:
            if tmp_path.exists():
                tmp_path.unlink()



class TestLaunchersAndScripts(unittest.TestCase):
    """5. Windows 启动脚本编码与稳定性防回归测试"""

    def test_batch_and_vbs_are_pure_ascii(self):
        """确保所有 .bat 和 .vbs 为 100% 纯 ASCII，杜绝 Windows CMD/WScript 编码崩溃"""
        launcher_files = [
            "start.bat",
            "start_browser.bat",
            "start_desktop.bat",
            "start_desktop.vbs",
            "启动大屏(无黑框).vbs",
            "build_exe.bat"
        ]
        for name in launcher_files:
            file_path = BASE_DIR / name
            self.assertTrue(file_path.exists(), f"启动脚本不存在: {name}")
            raw_bytes = file_path.read_bytes()
            is_ascii = all(b < 128 for b in raw_bytes)
            self.assertTrue(is_ascii, f"启动脚本 {name} 包含非 ASCII 字符，会导致 CMD/WScript 编码损坏")

    def test_kill_port_owner_zero_subprocess(self):
        """测试端口清理函数在未占用时毫秒级瞬时退出，不调用外部进程"""
        from desktop import kill_port_owner
        import time
        t0 = time.time()
        # 探测一个极大概率未使用的随机高端端口
        kill_port_owner(59876)
        elapsed = time.time() - t0
        self.assertLess(elapsed, 0.2, f"kill_port_owner 未占用时耗时过长: {elapsed:.3f}s")

    def test_desktop_python_compilation(self):
        """确保 desktop.py, desktop_tray.py 和 run.py 可无错误编译"""
        import py_compile
        for script in ["desktop.py", "desktop_tray.py", "run.py"]:
            script_path = BASE_DIR / script
            try:
                py_compile.compile(str(script_path), doraise=True)
            except py_compile.PyCompileError as e:
                self.fail(f"{script} 语法编译失败: {e}")

    def test_tray_metrics_and_autostart_logic(self):
        """测试系统托盘提示文案长度限制与开机自启检查逻辑"""
        if sys.platform == "win32":
            from desktop_tray import DesktopTrayManager, is_autostart_enabled
            # 创建虚拟 window 对象测试
            class MockWindow:
                class Events:
                    shown = []
                    closing = []
                events = Events()
                uid = "test-uid"

            manager = DesktopTrayManager(MockWindow())
            metrics_text = manager.get_metrics_text()
            self.assertIsInstance(metrics_text, str)
            self.assertLess(len(metrics_text), 64, f"托盘文案超过 Windows 63 字符严格限制: {metrics_text}")
            self.assertIsInstance(is_autostart_enabled(), bool)

    def test_tray_icon_rendering_and_gdi_cleanup(self):
        """测试托盘原生高质感 Indigo 图标动态渲染与 GDI 句柄释放"""
        if sys.platform == "win32":
            from desktop_tray import DesktopTrayManager

            class MockWindow:
                class Events:
                    shown = []
                    closing = []
                events = Events()
                uid = "test-uid-icon"

            manager = DesktopTrayManager(MockWindow())
            icon = manager._create_app_icon()
            self.assertIsNotNone(icon, "动态生成托盘图标失败")
            self.assertEqual(icon.Width, 32, "托盘图标宽度应为 32px 高清 ARGB 格式")
            self.assertEqual(icon.Height, 32, "托盘图标高度应为 32px 高清 ARGB 格式")
            self.assertIsNotNone(manager._created_hicon, "Win32 GDI HICON 句柄未正确托管")
            self.assertIsNotNone(manager._tray_icon, "托盘 Icon 实例未正确托管")

            # 测试 GDI 句柄释放与清理
            manager.dispose()
            self.assertIsNone(manager._created_hicon, "dispose() 后 GDI HICON 句柄未被置空销毁")
            self.assertIsNone(manager._tray_icon, "dispose() 后托盘 Icon 实例未被置空销毁")

    def test_tray_data_folder_and_alert_logic(self):
        """测试系统托盘打开数据目录接口与配额耗尽预警逻辑无异常"""
        if sys.platform == "win32":
            from desktop_tray import DesktopTrayManager

            class MockWindow:
                class Events:
                    shown = []
                    closing = []
                events = Events()
                uid = "test-uid-folder"

            manager = DesktopTrayManager(MockWindow())
            self.assertTrue(hasattr(manager, "open_data_folder"))
            self.assertTrue(hasattr(manager, "_check_quota_alert"))
            self.assertEqual(manager._last_alert_time, 0)
            # 执行一次检查，确保无异常抛出
            manager._check_quota_alert()


if __name__ == "__main__":
    unittest.main(verbosity=2)
