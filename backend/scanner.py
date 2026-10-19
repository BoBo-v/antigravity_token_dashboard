#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Antigravity Token 聚合分析引擎与数据缓存服务
负责会话扫描、时间窗口筛选、时序聚合、模型细分与缓存加速
"""

import io
import csv
import time
import sqlite3
import threading
from pathlib import Path
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Any
from collections import defaultdict

from .parser import read_conversation_db, MODEL_PLACEHOLDER_MAP
from .codex_parser import read_codex_session
from .claude_parser import read_claude_session
from .pricing import calculate_costs


class TokenScannerService:
    def __init__(self, root_override: Optional[str] = None):
        self.root_override = root_override
        # 缓存：db_path -> {"mtime": float, "records": list, "session_id": str, "source": str}
        self._db_cache: Dict[str, Dict[str, Any]] = {}
        # 会话元数据缓存：session_id -> dict
        self._summary_meta: Dict[str, Dict[str, Any]] = {}
        self.last_scan_time: Optional[datetime] = None
        self.total_db_count: int = 0
        self._last_scan_ts: float = 0.0
        self._official_usage_cache: Optional[Dict[str, Any]] = None
        self._official_usage_time: float = 0.0
        self._official_usage_error = None
        self._lock = threading.RLock()
        self._official_lock = threading.Lock()
        self.pricing_config = {"models": {}, "exchange_rate": 7.23}

    def get_gemini_root(self) -> Path:
        """获取 Antigravity 配置与会话根目录"""
        import os
        if self.root_override:
            p = Path(self.root_override).expanduser()
            if p.exists():
                return p
        env_val = os.environ.get("GEMINI_CLI_HOME")
        if env_val:
            p = Path(env_val).expanduser()
            if p.exists():
                return p
        return Path.home() / ".gemini"

    def get_codex_root(self) -> Path:
        """获取 OpenAI Codex 配置与会话根目录"""
        import os
        env_val = os.environ.get("CODEX_HOME")
        if env_val:
            p = Path(env_val).expanduser()
            if p.exists():
                return p
        return Path.home() / ".codex"

    def get_claude_root(self) -> Path:
        """获取 Anthropic Claude Code 配置与会话根目录"""
        import os
        env_val = os.environ.get("CLAUDE_CONFIG_DIR") or os.environ.get("CLAUDE_HOME")
        if env_val:
            p = Path(env_val).expanduser()
            if p.exists():
                return p
        return Path.home() / ".claude"

    def load_conversation_summaries(self, gemini_root: Path):
        """读取 conversation_summaries.db 获取每个 Antigravity 会话的人类可读标题、工作区与预览"""
        summaries_path = gemini_root / "antigravity-cli" / "conversation_summaries.db"
        if not summaries_path.exists():
            return

        uri = f"{summaries_path.resolve().as_uri()}?mode=ro"
        try:
            conn = sqlite3.connect(uri, uri=True, timeout=2.0)
        except Exception:
            try:
                conn = sqlite3.connect(str(summaries_path), timeout=2.0)
            except Exception:
                return

        try:
            cur = conn.cursor()
            cur.execute("SELECT conversation_id, title, preview, last_modified_time, workspace_uris FROM conversation_summaries")
            for cid, title, prev, last_mod, w_uris in cur.fetchall():
                self._summary_meta[cid] = {
                    "title": title or "未命名会话",
                    "preview": prev or "",
                    "last_modified_time": str(last_mod) if last_mod else "",
                    "workspace_uris": w_uris or ""
                }
        except Exception:
            pass
        finally:
            conn.close()

    def load_codex_summaries(self, codex_root: Path):
        """读取 codex-dev.db 获取每个 Codex 线程的标题与工作区"""
        db_path = codex_root / "sqlite" / "codex-dev.db"
        if not db_path.exists():
            return
        uri = f"{db_path.resolve().as_uri()}?mode=ro"
        try:
            conn = sqlite3.connect(uri, uri=True, timeout=2.0)
        except Exception:
            try:
                conn = sqlite3.connect(str(db_path), timeout=2.0)
            except Exception:
                return

        try:
            cur = conn.cursor()
            cur.execute("SELECT thread_id, display_title, cwd FROM local_thread_catalog")
            for tid, title, cwd in cur.fetchall():
                if tid:
                    self._summary_meta[tid] = {
                        "title": title or tid[:12],
                        "preview": "",
                        "last_modified_time": "",
                        "workspace_uris": cwd or ""
                    }
        except Exception:
            pass
        finally:
            conn.close()

    def load_claude_summaries(self, claude_root: Path):
        """读取 history.jsonl 获取每个 Claude Code 会话的标题与工作区"""
        import json
        hist_path = claude_root / "history.jsonl"
        if not hist_path.exists():
            return
        try:
            with open(hist_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    try:
                        obj = json.loads(line)
                        sid = obj.get("sessionId")
                        disp = obj.get("display")
                        proj = obj.get("project")
                        if sid and disp and sid not in self._summary_meta:
                            self._summary_meta[sid] = {
                                "title": disp.strip(),
                                "preview": "",
                                "last_modified_time": "",
                                "workspace_uris": proj or ""
                            }
                    except Exception:
                        pass
        except Exception:
            pass

    def discover_db_files(self, gemini_root: Path) -> List[Path]:
        """搜寻所有 Antigravity 会话数据库文件"""
        if not gemini_root.exists():
            return []
        found = {}
        for db_path in gemini_root.rglob("*.db"):
            if not db_path.is_file():
                continue
            path_str = str(db_path)
            # 排除备份目录与总表
            if "antigravity-backup" in path_str or db_path.name == "conversation_summaries.db":
                continue
            found[str(db_path.resolve())] = db_path
        return sorted(found.values(), key=lambda p: p.stat().st_mtime, reverse=True)

    def discover_codex_files(self, codex_root: Path) -> List[Path]:
        """搜寻所有 OpenAI Codex 会话 .jsonl 与 .jsonl.zst 文件"""
        found = []
        for sessions_dir in (codex_root / "sessions", codex_root / "archived_sessions"):
            if not sessions_dir.exists():
                continue
            for p in sessions_dir.rglob("*"):
                if p.is_file() and (p.name.endswith(".jsonl") or p.name.endswith(".jsonl.zst")):
                    found.append(p)
        return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)

    def discover_claude_files(self, claude_root: Path) -> List[Path]:
        """搜寻所有 Anthropic Claude Code 会话 .jsonl 文件"""
        projects_dir = claude_root / "projects"
        if not projects_dir.exists():
            return []
        found = []
        for p in projects_dir.rglob("*.jsonl"):
            if p.is_file():
                found.append(p)
        return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)

    def scan(self, force: bool = False):
        with self._lock:
            self._scan(force)

    @staticmethod
    def _fingerprint(path):
        def state(candidate):
            try:
                stat = candidate.stat()
                return stat.st_mtime_ns, stat.st_size
            except FileNotFoundError:
                return None
        return state(path), state(path.with_name(path.name + "-wal")) if path.suffix == ".db" else None

    def _scan(self, force: bool = False):
        """执行全量/增量扫描，跨 Antigravity、Codex 与 Claude Code，使用文件 mtime 进行高效缓存"""
        gemini_root = self.get_gemini_root()
        codex_root = self.get_codex_root()
        claude_root = self.get_claude_root()

        # 1. 载入各平台的会话标题与元数据字典
        if gemini_root.exists():
            self.load_conversation_summaries(gemini_root)
        if codex_root.exists():
            self.load_codex_summaries(codex_root)
        if claude_root.exists():
            self.load_claude_summaries(claude_root)

        # 2. 发现各工具会话文件
        gemini_files = self.discover_db_files(gemini_root) if gemini_root.exists() else []
        codex_files = self.discover_codex_files(codex_root) if codex_root.exists() else []
        claude_files = self.discover_claude_files(claude_root) if claude_root.exists() else []

        self.total_db_count = len(gemini_files) + len(codex_files) + len(claude_files)

        current_db_paths = set()
        title_dict = {k: v["title"] for k, v in self._summary_meta.items()}

        # 2.1 扫描 Antigravity (.db)
        for db_path in gemini_files:
            p_str = str(db_path.resolve())
            current_db_paths.add(p_str)
            try:
                mtime = db_path.stat().st_mtime
                fingerprint = self._fingerprint(db_path)
            except Exception:
                continue

            # 命中缓存检查
            if not force and p_str in self._db_cache:
                if self._db_cache[p_str].get("fingerprint") == fingerprint:
                    continue

            # 重新解析
            records = read_conversation_db(db_path)
            session_id = db_path.stem
            source_app = "antigravity"

            meta = self._summary_meta.get(session_id, {})
            session_title = meta.get("title", session_id[:12])

            for r in records:
                r["session_id"] = session_id
                r["session_title"] = session_title
                r["source_app"] = source_app

            self._db_cache[p_str] = {
                "fingerprint": fingerprint,
                "mtime": mtime,
                "session_id": session_id,
                "session_title": session_title,
                "source_app": source_app,
                "last_modified": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "records": records,
                "db_path": p_str
            }

        # 2.2 扫描 OpenAI Codex (.jsonl.zst)
        for zst_path in codex_files:
            p_str = str(zst_path.resolve())
            current_db_paths.add(p_str)
            try:
                mtime = zst_path.stat().st_mtime
                fingerprint = self._fingerprint(zst_path)
            except Exception:
                continue

            if not force and p_str in self._db_cache:
                if self._db_cache[p_str].get("fingerprint") == fingerprint:
                    continue

            records = read_codex_session(zst_path, title_dict)
            session_id = records[0]["session_id"] if records else zst_path.stem
            session_title = records[0]["session_title"] if records else session_id[:12]

            self._db_cache[p_str] = {
                "fingerprint": fingerprint,
                "mtime": mtime,
                "session_id": session_id,
                "session_title": session_title,
                "source_app": "codex",
                "last_modified": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "records": records,
                "db_path": p_str
            }

        # 2.3 扫描 Anthropic Claude Code (.jsonl)
        for jsonl_path in claude_files:
            p_str = str(jsonl_path.resolve())
            current_db_paths.add(p_str)
            try:
                mtime = jsonl_path.stat().st_mtime
                fingerprint = self._fingerprint(jsonl_path)
            except Exception:
                continue

            if not force and p_str in self._db_cache:
                if self._db_cache[p_str].get("fingerprint") == fingerprint:
                    continue

            records = read_claude_session(jsonl_path, title_dict)
            session_id = records[0]["session_id"] if records else jsonl_path.stem
            session_title = records[0]["session_title"] if records else session_id[:12]

            self._db_cache[p_str] = {
                "fingerprint": fingerprint,
                "mtime": mtime,
                "session_id": session_id,
                "session_title": session_title,
                "source_app": "claude-code",
                "last_modified": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "records": records,
                "db_path": p_str
            }

        # 清除已删除的文件缓存
        removed = [p for p in self._db_cache if p not in current_db_paths]
        for p in removed:
            del self._db_cache[p]

        self.last_scan_time = datetime.now()
        self._last_scan_ts = time.time()

    def get_all_turns(self, force_scan: bool = False, max_cache_age: float = 3.0) -> List[Dict[str, Any]]:
        """获取当前缓存中所有解析好的轮次，按会话去重；超过 max_cache_age 自动触发轻量增量扫描"""
        now = time.time()
        if force_scan or not self._db_cache or (now - getattr(self, "_last_scan_ts", 0.0) >= max_cache_age):
            self.scan(force=force_scan)

        merged = {}
        count_fields = ("input_tokens", "cache_read_tokens", "cache_write_tokens",
                        "thinking_tokens", "response_tokens", "total_output_tokens", "total_tokens")
        with self._lock:
            for item in self._db_cache.values():
                for record in item["records"]:
                    key = (record.get("source_app", "antigravity"), record["session_id"],
                           record.get("response_id") or record.get("gen_uuid") or record["turn_idx"])
                    if key not in merged:
                        merged[key] = dict(record)
                    elif record.get("source_app") == "claude-code":
                        previous = merged[key]
                        for field in count_fields:
                            previous[field] = max(previous.get(field, 0), record.get(field, 0))
                        previous["total_output_tokens"] = previous["response_tokens"]
                        previous["total_tokens"] = sum(previous[f] for f in
                            ("input_tokens", "cache_read_tokens", "cache_write_tokens", "total_output_tokens"))
        return list(merged.values())

    def filter_turns(self, turns: List[Dict[str, Any]], time_range: str, start_date: Optional[str] = None, end_date: Optional[str] = None, source: Optional[str] = "all") -> List[Dict[str, Any]]:
        """
        按时间与工具来源筛选记录：
        - source: 'all' 全部，或 'antigravity', 'codex', 'claude-code'
        - today: 今日 00:00:00 至今
        - yesterday: 昨日 00:00:00 至 23:59:59
        - week: 最近 7 天
        - month: 最近 30 天 / 当月
        - all: 全部
        - custom: start_date 至 end_date
        """
        if source and source != "all":
            turns = [t for t in turns if t.get("source_app") == source]

        now = datetime.now()
        today_date = now.date()
        today_str = today_date.strftime("%Y-%m-%d")

        if time_range == "today":
            return [t for t in turns if t["date_str"] == today_str]

        elif time_range == "yesterday":
            yesterday_str = (today_date - timedelta(days=1)).strftime("%Y-%m-%d")
            return [t for t in turns if t["date_str"] == yesterday_str]

        elif time_range == "week":
            week_start_sec = int((datetime.combine(today_date - timedelta(days=6), datetime.min.time())).timestamp())
            return [t for t in turns if t["timestamp_sec"] >= week_start_sec]

        elif time_range == "month":
            month_start_sec = int((datetime.combine(today_date - timedelta(days=29), datetime.min.time())).timestamp())
            return [t for t in turns if t["timestamp_sec"] >= month_start_sec]

        elif time_range == "custom":
            res = turns
            if start_date:
                res = [t for t in res if t["date_str"] >= start_date]
            if end_date:
                res = [t for t in res if t["date_str"] <= end_date]
            return res

        # 'all' 或未匹配
        return turns

    def calculate_summary(self, turns: List[Dict[str, Any]]) -> Dict[str, Any]:
        """计算 KPI 核心概览统计数据，支持 Antigravity、Codex 和 Claude Code 多源聚合"""
        total_tokens = sum(t["total_tokens"] for t in turns)
        input_tokens = sum(t["input_tokens"] for t in turns)
        cache_read_tokens = sum(t["cache_read_tokens"] for t in turns)
        cache_write_tokens = sum(t["cache_write_tokens"] for t in turns)
        thinking_tokens = sum(t["thinking_tokens"] for t in turns)
        response_tokens = sum(t["response_tokens"] for t in turns)
        total_output_tokens = sum(t["total_output_tokens"] for t in turns)

        total_prompt = input_tokens + cache_read_tokens + cache_write_tokens
        cache_hit_rate = round((cache_read_tokens / total_prompt * 100), 2) if total_prompt > 0 else 0.0

        distinct_sessions = len(set((t.get("source_app", "antigravity"), t["session_id"]) for t in turns))
        turns_count = len(turns)
        avg_per_turn = round(total_tokens / turns_count) if turns_count > 0 else 0

        valid_speeds = [t.get("speed_tps", 0) for t in turns if t.get("speed_tps", 0) > 0]
        avg_speed_tps = round(sum(valid_speeds) / len(valid_speeds), 1) if valid_speeds else 0.0

        valid_durs = [t.get("duration_sec", 0) for t in turns if t.get("duration_sec", 0) > 0]
        avg_duration_sec = round(sum(valid_durs) / len(valid_durs), 2) if valid_durs else 0.0

        # 按工具来源拆分统计
        by_source_tmp = defaultdict(lambda: {"total_tokens": 0, "turns_count": 0, "_sessions": set()})
        for t in turns:
            src = t.get("source_app", "antigravity")
            by_source_tmp[src]["total_tokens"] += t["total_tokens"]
            by_source_tmp[src]["turns_count"] += 1
            by_source_tmp[src]["_sessions"].add(t["session_id"])

        by_source = {}
        for src, d in by_source_tmp.items():
            by_source[src] = {
                "total_tokens": d["total_tokens"],
                "turns_count": d["turns_count"],
                "sessions_count": len(d["_sessions"]),
            }

        return {
            "total_tokens": total_tokens,
            "input_tokens": input_tokens,
            "cache_read_tokens": cache_read_tokens,
            "cache_write_tokens": cache_write_tokens,
            "thinking_tokens": thinking_tokens,
            "response_tokens": response_tokens,
            "total_output_tokens": total_output_tokens,
            "cache_hit_rate": cache_hit_rate,
            "sessions_count": distinct_sessions,
            "turns_count": turns_count,
            "avg_tokens_per_turn": avg_per_turn,
            "avg_speed_tps": avg_speed_tps,
            "avg_duration_sec": avg_duration_sec,
            "by_source": by_source,
            "costs": calculate_costs(turns, self.pricing_config),
        }

    def calculate_quotas(self, all_turns, custom_quota=None, official_quotas=None, source="all"):
        """Local windows are usage statistics, never a proxy for provider quota."""
        now = datetime.now()
        now_ts = int(now.timestamp())
        turns = [t for t in all_turns if t["timestamp_sec"] <= now_ts
                 and (source in (None, "all") or t.get("source_app") == source)]
        turns_5h = [t for t in turns if t["timestamp_sec"] > now_ts - 5 * 3600]
        monday = now.date() - timedelta(days=now.weekday())
        monday_ts = int(datetime.combine(monday, datetime.min.time()).timestamp())
        turns_week = [t for t in turns if t["timestamp_sec"] >= monday_ts]
        turns_7d = [t for t in turns if t["timestamp_sec"] > now_ts - 7 * 86400]
        next_monday = monday + timedelta(days=7)
        next_monday_ts = int(datetime.combine(next_monday, datetime.min.time()).timestamp())
        models = defaultdict(int)
        for turn in turns_5h:
            models[turn["model"]] += turn["total_tokens"]
        earliest = min((t["timestamp_sec"] for t in turns_5h), default=None)

        def snapshot(name):
            cfg = (custom_quota or {}).get(name, {})
            pct = cfg.get("remaining_pct")
            calibrated = cfg.get("calibrated_at") or 0
            reset_at = calibrated + (cfg.get("reset_seconds") or 0)
            expired = reset_at > 0 and reset_at <= now_ts
            return {
                "source": "manual" if pct is not None else "unknown",
                "remaining_pct": None if expired else pct,
                "calibrated_at": calibrated, "reset_at": reset_at or None,
                "expired": expired, "reset_seconds": max(0, reset_at - now_ts),
            }

        return {
            "source": source or "all",
            "quota_5h": {
                "used_tokens": sum(t["total_tokens"] for t in turns_5h),
                "calls": len(turns_5h),
                "input_tokens": sum(t["input_tokens"] + t["cache_read_tokens"] + t.get("cache_write_tokens", 0) for t in turns_5h),
                "output_tokens": sum(t["total_output_tokens"] for t in turns_5h),
                "models": dict(models),
                "next_relief_seconds": earliest + 5 * 3600 - now_ts if earliest is not None else 0,
                "next_relief_tokens": sum(t["total_tokens"] for t in turns_5h if t["timestamp_sec"] == earliest),
                "window_start": datetime.fromtimestamp(now_ts - 5 * 3600).strftime("%H:%M"),
                "window_end": now.strftime("%H:%M"),
                "dynamic": None, "snapshot": snapshot("quota_5h"),
            },
            "quota_week": {
                "used_tokens": sum(t["total_tokens"] for t in turns_week),
                "calls": len(turns_week),
                "weekly_reset_seconds": max(0, next_monday_ts - now_ts),
                "monday_date": monday.isoformat(),
                "next_reset_date": next_monday.strftime("%Y-%m-%d 00:00"),
                "tokens_7d_rolling": sum(t["total_tokens"] for t in turns_7d),
                "daily_burn_rate": round(sum(t["total_tokens"] for t in turns_7d) / 7),
                "dynamic": None, "snapshot": snapshot("quota_week"),
            },
        }

    def fetch_official_agy_usage(self, force: bool = False) -> Dict[str, Any]:
        with self._official_lock:
            result = self._fetch_official_agy_usage(force)
            self._official_usage_error = None if result.get("success") else result.get("error")
            return result

    def get_official_usage_snapshot(self):
        if not self._official_usage_cache:
            return None
        age = max(0, int(time.time() - self._official_usage_time))
        return {**self._official_usage_cache, "age_seconds": age,
                "stale": age >= 120 or bool(self._official_usage_error),
                "error": self._official_usage_error}

    def _fetch_official_agy_usage(self, force: bool = False) -> Dict[str, Any]:
        """
        调用官方 agy.exe -p /usage --output-format json
        直接获取官方云端实时订阅配额（Gemini 与 Claude 模型组的 5H / 周额度百分比与重置时间）
        默认带 120 秒内存缓存加速
        """
        import time
        import os
        import json
        import shutil
        import subprocess

        now = time.time()
        if not force and not self._official_usage_error and self._official_usage_cache and (now - self._official_usage_time < 120):
            return self.get_official_usage_snapshot()

        agy_path = shutil.which("agy")
        if not agy_path:
            candidate = Path.home() / "AppData" / "Local" / "agy" / "bin" / "agy.exe"
            if candidate.exists():
                agy_path = str(candidate)

        if not agy_path:
            return {"success": False, "error": "未在系统中找到 agy.exe 可执行文件"}

        try:
            cmd = [agy_path, "-p", "/usage", "--output-format", "json"]
            startupinfo = None
            creationflags = 0
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=45,
                startupinfo=startupinfo,
                creationflags=creationflags,
                encoding="utf-8",
                errors="ignore"
            )
            if res.returncode != 0:
                return {"success": False, "error": f"agy 查询失败: {res.stderr[:200]}"}

            raw = json.loads(res.stdout)
            cmd_data = raw.get("command", {}).get("data", {})
            groups = cmd_data.get("groups", [])
            if not isinstance(groups, list) or not groups:
                raise ValueError("官方响应未包含有效配额分组")

            parsed_groups = []
            for g in groups:
                g_item = {
                    "name": g.get("name", "未命名模型组"),
                    "description": g.get("description", ""),
                    "buckets": []
                }
                for b in g.get("buckets", []):
                    rem_frac = b.get("remaining_fraction")
                    if isinstance(rem_frac, bool) or not isinstance(rem_frac, (int, float)) or not 0 <= rem_frac <= 1:
                        raise ValueError("官方响应缺少有效 remaining_fraction")
                    rem_pct = round(rem_frac * 100, 1)
                    used_pct = round((1.0 - rem_frac) * 100, 1)
                    g_item["buckets"].append({
                        "id": b.get("id"),
                        "name": b.get("name"),
                        "window": b.get("window"),
                        "remaining_pct": rem_pct,
                        "used_pct": used_pct,
                        "reset_time": b.get("reset_time", ""),
                        "desc": b.get("description", "")
                    })
                parsed_groups.append(g_item)

            if not any(g["buckets"] for g in parsed_groups):
                raise ValueError("官方响应未包含有效配额项")
            now = time.time()
            result = {
                "success": True,
                "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "fetched_at_sec": int(now),
                "stale": False,
                "description": cmd_data.get("description", ""),
                "groups": parsed_groups
            }
            self._official_usage_cache = result
            self._official_usage_time = now
            return result

        except Exception as e:
            return {"success": False, "error": f"执行 agy /usage 异常: {str(e)}"}

    def calculate_trend(self, turns: List[Dict[str, Any]], time_range: str) -> List[Dict[str, Any]]:
        """
        计算时序折线图数据：
        - today / yesterday: 按 00:00 ~ 23:00 聚合（包含未发生的整点或自适应）
        - week / month / all / custom: 按日期 %Y-%m-%d 聚合
        """
        if time_range in ("today", "yesterday"):
            # 按小时聚合
            hourly_map = defaultdict(lambda: {
                "input": 0, "cache_read": 0, "cache_write": 0, "thinking": 0, "response": 0, "total": 0, "calls": 0
            })
            for t in turns:
                h_key = f"{t['hour_num']:02d}:00"
                bucket = hourly_map[h_key]
                bucket["input"] += t["input_tokens"]
                bucket["cache_read"] += t["cache_read_tokens"]
                bucket["cache_write"] += t.get("cache_write_tokens", 0)
                bucket["thinking"] += t["thinking_tokens"]
                bucket["response"] += t["response_tokens"]
                bucket["total"] += t["total_tokens"]
                bucket["calls"] += 1

            # 填充全天 24 小时轴
            trend = []
            for h in range(24):
                h_key = f"{h:02d}:00"
                b = hourly_map.get(h_key, {
                    "input": 0, "cache_read": 0, "cache_write": 0, "thinking": 0, "response": 0, "total": 0, "calls": 0
                })
                trend.append({
                    "time": h_key,
                    "input": b["input"],
                    "cache_read": b["cache_read"],
                    "cache_write": b["cache_write"],
                    "thinking": b["thinking"],
                    "response": b["response"],
                    "total": b["total"],
                    "calls": b["calls"],
                })
            return trend

        else:
            # 按天聚合
            daily_map = defaultdict(lambda: {
                "input": 0, "cache_read": 0, "cache_write": 0, "thinking": 0, "response": 0, "total": 0, "calls": 0
            })
            for t in turns:
                d_key = t["date_str"]
                bucket = daily_map[d_key]
                bucket["input"] += t["input_tokens"]
                bucket["cache_read"] += t["cache_read_tokens"]
                bucket["cache_write"] += t.get("cache_write_tokens", 0)
                bucket["thinking"] += t["thinking_tokens"]
                bucket["response"] += t["response_tokens"]
                bucket["total"] += t["total_tokens"]
                bucket["calls"] += 1

            trend = []
            for d_key in sorted(daily_map.keys()):
                b = daily_map[d_key]
                trend.append({
                    "time": d_key,
                    "input": b["input"],
                    "cache_read": b["cache_read"],
                    "cache_write": b["cache_write"],
                    "thinking": b["thinking"],
                    "response": b["response"],
                    "total": b["total"],
                    "calls": b["calls"],
                })
            return trend

    def calculate_models(self, turns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """计算模型维度的消耗占比与明细"""
        model_map = defaultdict(lambda: {
            "calls": 0, "input": 0, "cache_read": 0, "cache_write": 0, "thinking": 0, "response": 0, "total": 0
        })
        for t in turns:
            m = model_map[t["model"]]
            m["calls"] += 1
            m["input"] += t["input_tokens"]
            m["cache_read"] += t["cache_read_tokens"]
            m["cache_write"] += t.get("cache_write_tokens", 0)
            m["thinking"] += t["thinking_tokens"]
            m["response"] += t["response_tokens"]
            m["total"] += t["total_tokens"]

        grand_total = sum(m["total"] for m in model_map.values())
        models_list = []
        for name, st in sorted(model_map.items(), key=lambda x: x[1]["total"], reverse=True):
            pct = round((st["total"] / grand_total * 100), 1) if grand_total > 0 else 0.0
            models_list.append({
                "model": name,
                "calls": st["calls"],
                "input_tokens": st["input"],
                "cache_read_tokens": st["cache_read"],
                "cache_write_tokens": st["cache_write"],
                "thinking_tokens": st["thinking"],
                "response_tokens": st["response"],
                "total_tokens": st["total"],
                "percentage": pct,
            })
        return models_list

    def get_sessions_table(self, turns: List[Dict[str, Any]], page: int = 1, page_size: int = 15, search: str = "", source: Optional[str] = "all") -> Dict[str, Any]:
        """获取按会话聚合的数据列表，支持来源过滤、搜索、排序与分页"""
        if source and source != "all":
            turns = [t for t in turns if t.get("source_app") == source]

        session_groups = defaultdict(list)
        for t in turns:
            session_groups[(t.get("source_app", "antigravity"), t["session_id"])].append(t)

        rows = []
        for (source_app, sid), s_turns in session_groups.items():
            meta = self._summary_meta.get(sid, {})
            title = meta.get("title", s_turns[0].get("session_title", sid[:12]))
            workspace = meta.get("workspace_uris", "")
            models = sorted(set(t["model"] for t in s_turns))

            s_input = sum(t["input_tokens"] for t in s_turns)
            s_cache_r = sum(t["cache_read_tokens"] for t in s_turns)
            s_think = sum(t["thinking_tokens"] for t in s_turns)
            s_resp = sum(t["response_tokens"] for t in s_turns)
            s_tot = sum(t["total_tokens"] for t in s_turns)

            s_tot_out = sum(t.get("total_output_tokens", 0) for t in s_turns)
            if s_tot_out == 0:
                s_tot_out = s_think + s_resp

            session_costs = calculate_costs(s_turns, self.pricing_config)
            costs = session_costs["configured"]
            priced_turns = []
            for turn in s_turns:
                cost = calculate_costs([turn], self.pricing_config)["configured"]
                priced_turns.append({**turn, "cost_usd": cost["total_usd"],
                    "cost_promo_usd": cost["total_usd"], "cost_std_usd": cost["total_usd"],
                    "saved_promo_usd": cost["saved_usd"]})

            latest_ts = max(t["timestamp_sec"] for t in s_turns)
            latest_time_str = datetime.fromtimestamp(latest_ts).strftime("%Y-%m-%d %H:%M:%S")

            valid_speeds = [t.get("speed_tps", 0) for t in s_turns if t.get("speed_tps", 0) > 0]
            s_avg_speed = round(sum(valid_speeds) / len(valid_speeds), 1) if valid_speeds else 0.0
            s_dur = round(sum(t.get("duration_sec", 0) for t in s_turns), 2)

            rows.append({
                "session_id": sid,
                "title": title,
                "workspace": workspace,
                "source_app": s_turns[0].get("source_app", "antigravity"),
                "latest_time": latest_time_str,
                "latest_ts": latest_ts,
                "calls": len(s_turns),
                "models": models,
                "input_tokens": s_input,
                "cache_read_tokens": s_cache_r,
                "thinking_tokens": s_think,
                "response_tokens": s_resp,
                "total_tokens": s_tot,
                "cache_write_tokens": sum(t.get("cache_write_tokens", 0) for t in s_turns),
                "cost_usd": costs["total_usd"],
                "cost_promo_usd": costs["total_usd"],
                "cost_promo_cny": costs["total_cny"],
                "cost_std_usd": costs["total_usd"],
                "cost_saved_usd": costs["saved_usd"],
                "unpriced_turns": session_costs["unpriced_turns"],
                "avg_speed_tps": s_avg_speed,
                "total_duration_sec": s_dur,
                "turns": sorted(priced_turns, key=lambda x: (x["timestamp_sec"], x["turn_idx"])),
            })

        # 过滤搜索 (支持标题、会话ID、模型名称及工具来源)
        if search and isinstance(search, str) and search.strip():
            q = search.lower().strip()
            rows = [
                r for r in rows
                if q in r["title"].lower() or q in r["session_id"].lower() or q in r.get("source_app", "").lower() or any(q in m.lower() for m in r["models"])
            ]

        # 按最新活跃时间倒序
        rows.sort(key=lambda x: x["latest_ts"], reverse=True)

        total_count = len(rows)
        start = (page - 1) * page_size
        end = start + page_size
        paginated_rows = rows[start:end]

        return {
            "total": total_count,
            "page": page,
            "page_size": page_size,
            "items": paginated_rows,
        }

    def generate_csv_report(self, turns: List[Dict[str, Any]]) -> str:
        """导出符合当前时间筛选条件的详细轮次 CSV（带有 UTF-8 BOM）"""
        output = io.StringIO()
        output.write('\ufeff')  # UTF-8 BOM
        writer = csv.DictWriter(output, fieldnames=[
            "timestamp",
            "date",
            "session_id",
            "session_title",
            "source_app",
            "turn_idx",
            "model",
            "input_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
            "thinking_tokens",
            "response_tokens",
            "total_output_tokens",
            "total_tokens",
            "duration_sec",
            "speed_tps",
            "ttft_sec",
            "cost_promo_usd",
            "cost_std_usd",
            "cost_usd",
            "pricing_status",
            "response_id",
        ])
        writer.writeheader()
        for t in sorted(turns, key=lambda x: x["timestamp_sec"], reverse=True):
            t_in = t.get("input_tokens", 0)
            t_cache = t.get("cache_read_tokens", 0)
            t_out = t.get("total_output_tokens", 0)
            cost = calculate_costs([t], self.pricing_config)["configured"]
            cost_p = cost_s = cost["total_usd"]

            writer.writerow({
                "timestamp": t.get("timestamp_str", ""),
                "date": t.get("date_str", ""),
                "session_id": t.get("session_id", ""),
                "session_title": t.get("session_title", ""),
                "source_app": t.get("source_app", ""),
                "turn_idx": t.get("turn_idx", 0),
                "model": t.get("model", ""),
                "input_tokens": t_in,
                "cache_read_tokens": t_cache,
                "cache_write_tokens": t.get("cache_write_tokens", 0),
                "thinking_tokens": t.get("thinking_tokens", 0),
                "response_tokens": t.get("response_tokens", 0),
                "total_output_tokens": t_out,
                "total_tokens": t.get("total_tokens", 0),
                "duration_sec": t.get("duration_sec", 0),
                "speed_tps": t.get("speed_tps", 0),
                "ttft_sec": t.get("ttft_sec", ""),
                "cost_promo_usd": cost_p,
                "cost_std_usd": cost_s,
                "cost_usd": cost["total_usd"],
                "pricing_status": "unpriced" if cost["total_usd"] is None else "configured",
                "response_id": t.get("response_id", ""),
            })
        return output.getvalue()


# 全局单例服务
scanner_service = TokenScannerService()
