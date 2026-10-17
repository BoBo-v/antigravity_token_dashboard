#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Anthropic Claude Code 会话 (.jsonl) Token 解析模块
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any


def read_claude_session(jsonl_path: Path, titles_map: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """
    解析单个 Claude Code .jsonl 会话文件中的所有有效 Token 轮次记录
    """
    if not jsonl_path.is_file():
        return []

    records = []
    file_mtime = int(jsonl_path.stat().st_mtime)
    sid = jsonl_path.stem
    session_title = ""
    turn_idx = 0

    try:
        with open(jsonl_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue

                otype = obj.get("type")
                if otype == "user" and not session_title:
                    msg = obj.get("message", {})
                    if isinstance(msg, dict):
                        content = msg.get("content", "")
                        if isinstance(content, str) and content:
                            session_title = content[:60].strip()
                        elif isinstance(content, list) and content:
                            session_title = str(content[0].get("text", ""))[:60].strip()

                elif otype == "assistant":
                    msg = obj.get("message", {})
                    usage = msg.get("usage", {})
                    if not isinstance(usage, dict):
                        continue

                    in_tok = usage.get("input_tokens", 0)
                    cache_r = usage.get("cache_read_input_tokens", 0)
                    cache_w = usage.get("cache_creation_input_tokens", 0)
                    out_tok = usage.get("output_tokens", 0)
                    tot = in_tok + cache_r + cache_w + out_tok
                    model = msg.get("model", "claude-code")

                    # 排除占位或无 token 消耗错误项（如 <synthetic> 登录提示）
                    if tot <= 0 or model == "<synthetic>":
                        continue

                    ts_raw = obj.get("timestamp")
                    ts_sec = file_mtime
                    if ts_raw:
                        try:
                            dt = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                            ts_sec = int(dt.timestamp())
                        except Exception:
                            dt = datetime.fromtimestamp(ts_sec)
                    else:
                        dt = datetime.fromtimestamp(ts_sec)

                    turn_idx += 1
                    records.append({
                        "turn_idx": turn_idx,
                        "model": model,
                        "input_tokens": in_tok,
                        "cache_read_tokens": cache_r,
                        "cache_write_tokens": cache_w,
                        "thinking_tokens": 0,
                        "response_tokens": out_tok,
                        "total_output_tokens": out_tok,
                        "total_tokens": tot,
                        "response_id": msg.get("id") or f"claude_call_{turn_idx}",
                        "gen_uuid": f"claude_{sid}_{turn_idx}",
                        "timestamp_sec": ts_sec,
                        "timestamp_str": dt.strftime("%Y-%m-%d %H:%M:%S"),
                        "date_str": dt.strftime("%Y-%m-%d"),
                        "hour_str": dt.strftime("%Y-%m-%d %H:00"),
                        "hour_num": dt.hour,
                        "duration_sec": 0.0,
                        "ttft_sec": None,
                        "speed_tps": 0.0,
                        "source_app": "claude-code",
                    })
    except Exception:
        pass

    resolved_title = ""
    if titles_map and sid in titles_map:
        resolved_title = titles_map[sid]
    if not resolved_title:
        resolved_title = session_title or sid[:16]

    for r in records:
        r["session_id"] = sid
        r["session_title"] = resolved_title

    return records
