#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenAI Codex CLI 会话 (.jsonl.zst) 解码与 Token 解析模块
"""

import io
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any

try:
    import zstandard as zstd
    HAS_ZSTD = True
except ImportError:
    zstd = None
    HAS_ZSTD = False


def read_codex_session(zst_path: Path, titles_map: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """
    解析单个 Codex .jsonl.zst 会话文件中的所有 Token 轮次记录
    """
    if not HAS_ZSTD or not zst_path.is_file():
        return []

    records = []
    file_mtime = int(zst_path.stat().st_mtime)
    dctx = zstd.ZstdDecompressor()

    session_id = None
    session_title = ""
    current_model = "gpt-5.5"
    prev_total_tokens = 0
    turn_idx = 0

    try:
        with open(zst_path, "rb") as fh:
            with dctx.stream_reader(fh) as reader:
                text_stream = io.TextIOWrapper(reader, encoding="utf-8", errors="ignore")
                for line in text_stream:
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue

                    otype = obj.get("type")
                    payload = obj.get("payload", {})
                    ts_raw = obj.get("timestamp")

                    if otype == "session_meta" and isinstance(payload, dict):
                        session_id = payload.get("session_id") or payload.get("id")
                    elif otype == "turn_context" and isinstance(payload, dict):
                        if payload.get("model"):
                            current_model = payload.get("model")
                    elif otype == "response_item" and isinstance(payload, dict):
                        if payload.get("role") == "user" and not session_title:
                            content = payload.get("content", [])
                            if isinstance(content, list) and content:
                                txt = content[0].get("text", "")
                                if not txt.startswith("<environment_context>"):
                                    session_title = txt[:60].strip()
                    elif payload.get("type") == "token_count" and payload.get("info"):
                        info = payload["info"]
                        tot_usage = info.get("total_token_usage", {})
                        tot = tot_usage.get("total_tokens", 0)

                        # 只有当 total_tokens 严格递增时，才代表一次新的 LLM 调用完成（避免重复流事件）
                        if tot > prev_total_tokens:
                            last_u = info.get("last_token_usage", {})
                            in_tok = last_u.get("input_tokens", 0)
                            cache_r = last_u.get("cached_input_tokens", 0)
                            cache_w = last_u.get("cache_write_input_tokens", 0)
                            out_tok = last_u.get("output_tokens", 0)
                            think_tok = last_u.get("reasoning_output_tokens", 0)
                            call_tot = last_u.get("total_tokens", 0)

                            # 时间戳解析
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
                                "model": current_model,
                                "input_tokens": in_tok,
                                "cache_read_tokens": cache_r,
                                "cache_write_tokens": cache_w,
                                "thinking_tokens": think_tok,
                                "response_tokens": max(0, out_tok - think_tok),
                                "total_output_tokens": out_tok,
                                "total_tokens": call_tot or (in_tok + cache_r + cache_w + out_tok),
                                "response_id": f"codex_call_{turn_idx}",
                                "gen_uuid": f"codex_{zst_path.stem}_{turn_idx}",
                                "timestamp_sec": ts_sec,
                                "timestamp_str": dt.strftime("%Y-%m-%d %H:%M:%S"),
                                "date_str": dt.strftime("%Y-%m-%d"),
                                "hour_str": dt.strftime("%Y-%m-%d %H:00"),
                                "hour_num": dt.hour,
                                "duration_sec": 0.0,
                                "ttft_sec": None,
                                "speed_tps": 0.0,
                                "source_app": "codex",
                            })
                            prev_total_tokens = tot
    except Exception:
        pass

    # 若 session_id 未读取到，用文件名解析兜底
    if not session_id:
        stem = zst_path.name.replace(".jsonl.zst", "")
        parts = stem.split("-")
        if len(parts) >= 5:
            session_id = "-".join(parts[-5:])
        else:
            session_id = stem

    resolved_title = ""
    if titles_map and session_id in titles_map:
        resolved_title = titles_map[session_id]
    if not resolved_title:
        resolved_title = session_title or session_id[:16]

    for r in records:
        r["session_id"] = session_id
        r["session_title"] = resolved_title

    return records
