#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Antigravity Token 聚合分析引擎与数据缓存服务
负责会话扫描、时间窗口筛选、时序聚合、模型细分与缓存加速
"""

import io
import csv
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Any
from collections import defaultdict

from .parser import read_conversation_db, MODEL_PLACEHOLDER_MAP


class TokenScannerService:
    def __init__(self, root_override: Optional[str] = None):
        self.root_override = root_override
        # 缓存：db_path -> {"mtime": float, "records": list, "session_id": str, "source": str}
        self._db_cache: Dict[str, Dict[str, Any]] = {}
        # 会话元数据缓存：session_id -> dict
        self._summary_meta: Dict[str, Dict[str, Any]] = {}
        self.last_scan_time: Optional[datetime] = None
        self.total_db_count: int = 0
        self._official_usage_cache: Optional[Dict[str, Any]] = None
        self._official_usage_time: float = 0.0

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

    def load_conversation_summaries(self, gemini_root: Path):
        """读取 conversation_summaries.db 获取每个会话的人类可读标题、工作区与预览"""
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

    def scan(self, force: bool = False):
        """执行全量/增量扫描，使用文件 mtime 进行高效缓存"""
        gemini_root = self.get_gemini_root()
        if not gemini_root.exists():
            return

        # 1. 载入会话标题字典
        self.load_conversation_summaries(gemini_root)

        # 2. 发现所有会话 db
        db_files = self.discover_db_files(gemini_root)
        self.total_db_count = len(db_files)

        current_db_paths = set()
        for db_path in db_files:
            p_str = str(db_path.resolve())
            current_db_paths.add(p_str)
            try:
                st = db_path.stat()
                mtime = st.st_mtime
            except Exception:
                continue

            # 命中缓存检查
            if not force and p_str in self._db_cache:
                if self._db_cache[p_str]["mtime"] == mtime:
                    continue

            # 重新解析
            records = read_conversation_db(db_path)
            session_id = db_path.stem

            rel_parts = db_path.relative_to(gemini_root).parts
            source_app = rel_parts[0] if rel_parts else "antigravity"

            # 补全每条记录的 session 基础信息
            meta = self._summary_meta.get(session_id, {})
            session_title = meta.get("title", session_id[:12])

            for r in records:
                r["session_id"] = session_id
                r["session_title"] = session_title
                r["source_app"] = source_app

            self._db_cache[p_str] = {
                "mtime": mtime,
                "session_id": session_id,
                "session_title": session_title,
                "source_app": source_app,
                "last_modified": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "records": records,
                "db_path": p_str
            }

        # 清除已删除的文件缓存
        removed = [p for p in self._db_cache if p not in current_db_paths]
        for p in removed:
            del self._db_cache[p]

        self.last_scan_time = datetime.now()

    def get_all_turns(self) -> List[Dict[str, Any]]:
        """获取当前缓存中所有解析好的轮次，按会话去重"""
        if not self._db_cache:
            self.scan()
        processed_sessions = set()
        all_turns = []
        for p_str, item in self._db_cache.items():
            sid = item["session_id"]
            if sid in processed_sessions:
                continue
            processed_sessions.add(sid)
            all_turns.extend(item["records"])
        return all_turns

    def filter_turns(self, turns: List[Dict[str, Any]], time_range: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        按时间筛选记录：
        - today: 今日 00:00:00 至今
        - yesterday: 昨日 00:00:00 至 23:59:59
        - week: 最近 7 天
        - month: 最近 30 天 / 当月
        - all: 全部
        - custom: start_date 至 end_date
        """
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
        """计算 KPI 核心概览统计数据"""
        total_tokens = sum(t["total_tokens"] for t in turns)
        input_tokens = sum(t["input_tokens"] for t in turns)
        cache_read_tokens = sum(t["cache_read_tokens"] for t in turns)
        cache_write_tokens = sum(t["cache_write_tokens"] for t in turns)
        thinking_tokens = sum(t["thinking_tokens"] for t in turns)
        response_tokens = sum(t["response_tokens"] for t in turns)
        total_output_tokens = sum(t["total_output_tokens"] for t in turns)

        total_prompt = input_tokens + cache_read_tokens
        cache_hit_rate = round((cache_read_tokens / total_prompt * 100), 2) if total_prompt > 0 else 0.0

        distinct_sessions = len(set(t["session_id"] for t in turns))
        turns_count = len(turns)
        avg_per_turn = round(total_tokens / turns_count) if turns_count > 0 else 0

        valid_speeds = [t.get("speed_tps", 0) for t in turns if t.get("speed_tps", 0) > 0]
        avg_speed_tps = round(sum(valid_speeds) / len(valid_speeds), 1) if valid_speeds else 0.0

        valid_durs = [t.get("duration_sec", 0) for t in turns if t.get("duration_sec", 0) > 0]
        avg_duration_sec = round(sum(valid_durs) / len(valid_durs), 2) if valid_durs else 0.0

        # 费用估计（根据用户提供的 2026 促销期与 2027 标准期百万 Token 定价标准）
        cost_promo_input = (input_tokens / 1000000) * 0.75
        cost_promo_cache = (cache_read_tokens / 1000000) * 0.0375
        cost_promo_output = (total_output_tokens / 1000000) * 3.75
        total_cost_promo = cost_promo_input + cost_promo_cache + cost_promo_output
        saved_promo = (cache_read_tokens / 1000000) * (0.75 - 0.0375)

        cost_std_input = (input_tokens / 1000000) * 1.50
        cost_std_cache = (cache_read_tokens / 1000000) * 0.075
        cost_std_output = (total_output_tokens / 1000000) * 7.50
        total_cost_std = cost_std_input + cost_std_cache + cost_std_output
        saved_std = (cache_read_tokens / 1000000) * (1.50 - 0.075)

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
            "costs": {
                "exchange_rate": 7.23,
                "promo": {
                    "total_usd": round(total_cost_promo, 4),
                    "total_cny": round(total_cost_promo * 7.23, 2),
                    "input_usd": round(cost_promo_input, 4),
                    "cache_usd": round(cost_promo_cache, 4),
                    "output_usd": round(cost_promo_output, 4),
                    "saved_usd": round(saved_promo, 4),
                    "saved_cny": round(saved_promo * 7.23, 2),
                },
                "standard": {
                    "total_usd": round(total_cost_std, 4),
                    "total_cny": round(total_cost_std * 7.23, 2),
                    "input_usd": round(cost_std_input, 4),
                    "cache_usd": round(cost_std_cache, 4),
                    "output_usd": round(cost_std_output, 4),
                    "saved_usd": round(saved_std, 4),
                    "saved_cny": round(saved_std * 7.23, 2),
                }
            }
        }

    def calculate_quotas(self, all_turns: List[Dict[str, Any]]) -> Dict[str, Any]:
        """计算 5小时滑动窗口额度与周限额监控数据"""
        now = datetime.now()
        now_ts = int(now.timestamp())

        # 1. 5小时滑动窗口 (5H Rolling Window)
        five_h_start = now_ts - 5 * 3600
        turns_5h = [t for t in all_turns if t["timestamp_sec"] >= five_h_start]
        tokens_5h = sum(t["total_tokens"] for t in turns_5h)
        calls_5h = len(turns_5h)
        input_5h = sum(t["input_tokens"] + t["cache_read_tokens"] for t in turns_5h)
        output_5h = sum(t["total_output_tokens"] for t in turns_5h)

        models_5h = defaultdict(int)
        for t in turns_5h:
            models_5h[t["model"]] += t["total_tokens"]

        next_relief_seconds = 0
        next_relief_tokens = 0
        if turns_5h:
            min_ts = min(t["timestamp_sec"] for t in turns_5h)
            relief_at = min_ts + 5 * 3600
            next_relief_seconds = max(0, relief_at - now_ts)
            # 最早一批（前 15 分钟内）的释放量预估
            next_relief_tokens = sum(t["total_tokens"] for t in turns_5h if t["timestamp_sec"] <= min_ts + 900)

        # 2. 自然周 (从周一 00:00:00 至今)
        today = now.date()
        monday = today - timedelta(days=today.weekday())
        monday_ts = int(datetime.combine(monday, datetime.min.time()).timestamp())
        turns_week = [t for t in all_turns if t["timestamp_sec"] >= monday_ts]
        tokens_week = sum(t["total_tokens"] for t in turns_week)
        calls_week = len(turns_week)

        # 距离下周一 00:00:00 重置倒计时
        next_monday = monday + timedelta(days=7)
        next_monday_ts = int(datetime.combine(next_monday, datetime.min.time()).timestamp())
        weekly_reset_seconds = max(0, next_monday_ts - now_ts)

        # 3. 滑动 7 天统计 (Past 7 Days Rolling)
        seven_d_start = now_ts - 7 * 86400
        turns_7d = [t for t in all_turns if t["timestamp_sec"] >= seven_d_start]
        tokens_7d = sum(t["total_tokens"] for t in turns_7d)

        # 日均燃烧率 (过去 7 天日均消耗)
        daily_burn_rate = round(tokens_7d / 7) if tokens_7d > 0 else 0

        return {
            "quota_5h": {
                "used_tokens": tokens_5h,
                "calls": calls_5h,
                "input_tokens": input_5h,
                "output_tokens": output_5h,
                "models": dict(models_5h),
                "next_relief_seconds": next_relief_seconds,
                "next_relief_tokens": next_relief_tokens,
                "window_start": datetime.fromtimestamp(five_h_start).strftime("%H:%M"),
                "window_end": now.strftime("%H:%M"),
            },
            "quota_week": {
                "used_tokens": tokens_week,
                "calls": calls_week,
                "weekly_reset_seconds": weekly_reset_seconds,
                "monday_date": monday.strftime("%Y-%m-%d"),
                "next_reset_date": next_monday.strftime("%Y-%m-%d 00:00"),
                "tokens_7d_rolling": tokens_7d,
                "daily_burn_rate": daily_burn_rate,
            }
        }

    def fetch_official_agy_usage(self, force: bool = False) -> Dict[str, Any]:
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
        if not force and self._official_usage_cache and (now - self._official_usage_time < 120):
            return self._official_usage_cache

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
                timeout=15,
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

            parsed_groups = []
            for g in groups:
                g_item = {
                    "name": g.get("name", "未命名模型组"),
                    "description": g.get("description", ""),
                    "buckets": []
                }
                for b in g.get("buckets", []):
                    rem_frac = b.get("remaining_fraction", 1.0)
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

            result = {
                "success": True,
                "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "description": cmd_data.get("description", ""),
                "groups": parsed_groups
            }
            self._official_usage_cache = result
            self._official_usage_time = now
            return result

        except Exception as e:
            if self._official_usage_cache:
                return self._official_usage_cache
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
                "input": 0, "cache_read": 0, "thinking": 0, "response": 0, "total": 0, "calls": 0
            })
            for t in turns:
                h_key = f"{t['hour_num']:02d}:00"
                bucket = hourly_map[h_key]
                bucket["input"] += t["input_tokens"]
                bucket["cache_read"] += t["cache_read_tokens"]
                bucket["thinking"] += t["thinking_tokens"]
                bucket["response"] += t["response_tokens"]
                bucket["total"] += t["total_tokens"]
                bucket["calls"] += 1

            # 填充全天 24 小时轴
            trend = []
            for h in range(24):
                h_key = f"{h:02d}:00"
                b = hourly_map.get(h_key, {
                    "input": 0, "cache_read": 0, "thinking": 0, "response": 0, "total": 0, "calls": 0
                })
                trend.append({
                    "time": h_key,
                    "input": b["input"],
                    "cache_read": b["cache_read"],
                    "thinking": b["thinking"],
                    "response": b["response"],
                    "total": b["total"],
                    "calls": b["calls"],
                })
            return trend

        else:
            # 按天聚合
            daily_map = defaultdict(lambda: {
                "input": 0, "cache_read": 0, "thinking": 0, "response": 0, "total": 0, "calls": 0
            })
            for t in turns:
                d_key = t["date_str"]
                bucket = daily_map[d_key]
                bucket["input"] += t["input_tokens"]
                bucket["cache_read"] += t["cache_read_tokens"]
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
                    "thinking": b["thinking"],
                    "response": b["response"],
                    "total": b["total"],
                    "calls": b["calls"],
                })
            return trend

    def calculate_models(self, turns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """计算模型维度的消耗占比与明细"""
        model_map = defaultdict(lambda: {
            "calls": 0, "input": 0, "cache_read": 0, "thinking": 0, "response": 0, "total": 0
        })
        for t in turns:
            m = model_map[t["model"]]
            m["calls"] += 1
            m["input"] += t["input_tokens"]
            m["cache_read"] += t["cache_read_tokens"]
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
                "thinking_tokens": st["thinking"],
                "response_tokens": st["response"],
                "total_tokens": st["total"],
                "percentage": pct,
            })
        return models_list

    def get_sessions_table(self, turns: List[Dict[str, Any]], page: int = 1, page_size: int = 15, search: str = "") -> Dict[str, Any]:
        """获取按会话聚合的数据列表，支持搜索、排序与分页"""
        session_groups = defaultdict(list)
        for t in turns:
            session_groups[t["session_id"]].append(t)

        rows = []
        for sid, s_turns in session_groups.items():
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

            # 费用计算（促销期与标准期，美元与人民币）
            cost_promo = (s_input / 1_000_000) * 0.75 + (s_cache_r / 1_000_000) * 0.0375 + (s_tot_out / 1_000_000) * 3.75
            cost_std = (s_input / 1_000_000) * 1.50 + (s_cache_r / 1_000_000) * 0.075 + (s_tot_out / 1_000_000) * 7.50
            cost_saved = (s_cache_r / 1_000_000) * (0.75 - 0.0375)

            # 给每个 turn 附加上预估费用
            for t in s_turns:
                t_in = t.get("input_tokens", 0)
                t_cache = t.get("cache_read_tokens", 0)
                t_out = t.get("total_output_tokens", 0) or (t.get("thinking_tokens", 0) + t.get("response_tokens", 0))
                t["cost_promo_usd"] = round((t_in / 1_000_000) * 0.75 + (t_cache / 1_000_000) * 0.0375 + (t_out / 1_000_000) * 3.75, 5)
                t["cost_std_usd"] = round((t_in / 1_000_000) * 1.50 + (t_cache / 1_000_000) * 0.075 + (t_out / 1_000_000) * 7.50, 5)
                t["saved_promo_usd"] = round((t_cache / 1_000_000) * (0.75 - 0.0375), 5)

            # 最新活跃时间
            latest_ts = max(t["timestamp_sec"] for t in s_turns)
            latest_time_str = datetime.fromtimestamp(latest_ts).strftime("%Y-%m-%d %H:%M:%S")

            valid_speeds = [t.get("speed_tps", 0) for t in s_turns if t.get("speed_tps", 0) > 0]
            s_avg_speed = round(sum(valid_speeds) / len(valid_speeds), 1) if valid_speeds else 0.0
            s_dur = round(sum(t.get("duration_sec", 0) for t in s_turns), 2)

            rows.append({
                "session_id": sid,
                "title": title,
                "workspace": workspace,
                "source_app": s_turns[0].get("source_app", "cli"),
                "latest_time": latest_time_str,
                "latest_ts": latest_ts,
                "calls": len(s_turns),
                "models": models,
                "input_tokens": s_input,
                "cache_read_tokens": s_cache_r,
                "thinking_tokens": s_think,
                "response_tokens": s_resp,
                "total_tokens": s_tot,
                "cost_promo_usd": round(cost_promo, 4),
                "cost_promo_cny": round(cost_promo * 7.23, 2),
                "cost_std_usd": round(cost_std, 4),
                "cost_saved_usd": round(cost_saved, 4),
                "avg_speed_tps": s_avg_speed,
                "total_duration_sec": s_dur,
                "turns": sorted(s_turns, key=lambda x: x["turn_idx"]),
            })

        # 过滤搜索
        if search and isinstance(search, str) and search.strip():
            q = search.lower().strip()
            rows = [
                r for r in rows
                if q in r["title"].lower() or q in r["session_id"].lower() or any(q in m.lower() for m in r["models"])
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
            "response_id",
        ])
        writer.writeheader()
        for t in sorted(turns, key=lambda x: x["timestamp_sec"], reverse=True):
            t_in = t.get("input_tokens", 0)
            t_cache = t.get("cache_read_tokens", 0)
            t_out = t.get("total_output_tokens", 0) or (t.get("thinking_tokens", 0) + t.get("response_tokens", 0))
            cost_p = round((t_in / 1_000_000) * 0.75 + (t_cache / 1_000_000) * 0.0375 + (t_out / 1_000_000) * 3.75, 5)
            cost_s = round((t_in / 1_000_000) * 1.50 + (t_cache / 1_000_000) * 0.075 + (t_out / 1_000_000) * 7.50, 5)

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
                "response_id": t.get("response_id", ""),
            })
        return output.getvalue()


# 全局单例服务
scanner_service = TokenScannerService()
