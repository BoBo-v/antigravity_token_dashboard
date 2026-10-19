#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Antigravity 会话数据库 (.db) Protobuf 解码器与元数据解析模块
零外部第三方依赖，专为高性能解析 gen_metadata 与 steps 设计。
"""

import os
import sqlite3
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Optional, Any, Tuple


# 模型占位符与常见模型映射表
MODEL_PLACEHOLDER_MAP = {
    "MODEL_PLACEHOLDER_M16": "Gemini 3.1 Pro (High)",
    "MODEL_PLACEHOLDER_M37": "Gemini 3.1 Pro (High)",
    "MODEL_PLACEHOLDER_M36": "Gemini 3.1 Pro (Low)",
    "MODEL_PLACEHOLDER_M84": "Gemini 3.5 Flash (High)",
    "MODEL_PLACEHOLDER_M18": "Gemini 3 Flash",
    "MODEL_PLACEHOLDER_M35": "Claude Sonnet 4.6",
    "MODEL_PLACEHOLDER_M26": "Claude Opus 4.6 (Thinking)",
    "1016": "Gemini 3.1 Pro (High)",
    "1037": "Gemini 3.1 Pro (High)",
    "1036": "Gemini 3.1 Pro (Low)",
    "1084": "Gemini 3.5 Flash (High)",
    "1018": "Gemini 3 Flash",
    "1035": "Claude Sonnet 4.6",
    "1026": "Claude Opus 4.6 (Thinking)",
}


def read_varint(buf: bytes, pos: int) -> Tuple[int, int]:
    """读取 Protobuf Varint 整数"""
    result = 0
    shift = 0
    length = len(buf)
    while pos < length:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7
        if shift >= 64:
            raise ValueError("Varint 长度溢出")
    raise ValueError("Varint 意外截断")


def parse_proto_message(buf: bytes) -> Dict[int, List[Tuple[int, Any]]]:
    """
    将 Protobuf 二进制流解析为 {field_number: [(wire_type, value), ...]} 字典
    """
    fields = defaultdict(list)
    pos = 0
    length = len(buf)
    while pos < length:
        try:
            tag, pos = read_varint(buf, pos)
        except ValueError:
            break
        field_num = tag >> 3
        wire_type = tag & 0x07
        if field_num <= 0:
            break

        if wire_type == 0:  # Varint
            try:
                val, pos = read_varint(buf, pos)
                fields[field_num].append((0, val))
            except ValueError:
                break
        elif wire_type == 1:  # 64-bit
            if pos + 8 > length:
                break
            fields[field_num].append((1, buf[pos:pos + 8]))
            pos += 8
        elif wire_type == 2:  # Length-delimited
            try:
                sub_len, pos = read_varint(buf, pos)
            except ValueError:
                break
            if sub_len < 0 or pos + sub_len > length:
                break
            fields[field_num].append((2, buf[pos:pos + sub_len]))
            pos += sub_len
        elif wire_type == 5:  # 32-bit
            if pos + 4 > length:
                break
            fields[field_num].append((5, buf[pos:pos + 4]))
            pos += 4
        else:
            break
    return fields


def get_first_varint(fields: Dict[int, List[Tuple[int, Any]]], field_num: int, default: int = 0) -> int:
    for wt, val in fields.get(field_num, []):
        if wt == 0:
            return val
    return default


def get_first_bytes(fields: Dict[int, List[Tuple[int, Any]]], field_num: int) -> bytes:
    for wt, val in fields.get(field_num, []):
        if wt == 2:
            return val
    return b""


def get_first_str(fields: Dict[int, List[Tuple[int, Any]]], field_num: int, default: str = "") -> str:
    raw = get_first_bytes(fields, field_num)
    if not raw:
        return default
    try:
        return raw.decode("utf-8", errors="ignore").strip()
    except Exception:
        return default


def resolve_model_name(chat_model_fields: dict, usage_fields: dict) -> str:
    """提取标准化、易读的模型名称"""
    display_name = get_first_str(chat_model_fields, 21)
    model_config_id = get_first_str(chat_model_fields, 19)

    model_enum_str = ""
    for wt, raw_kv in chat_model_fields.get(20, []):
        if wt == 2:
            kv = parse_proto_message(raw_kv)
            k = get_first_str(kv, 1)
            v = get_first_str(kv, 2)
            if k == "model_enum" and v:
                model_enum_str = v
                break

    if display_name and not display_name.startswith("MODEL_PLACEHOLDER"):
        return display_name

    if model_enum_str in MODEL_PLACEHOLDER_MAP:
        return MODEL_PLACEHOLDER_MAP[model_enum_str]

    usage_model_enum = str(get_first_varint(usage_fields, 1, 0))
    if usage_model_enum in MODEL_PLACEHOLDER_MAP:
        return MODEL_PLACEHOLDER_MAP[usage_model_enum]

    if model_config_id and model_enum_str:
        return f"{model_config_id} ({model_enum_str})"
    if model_config_id:
        return model_config_id
    if model_enum_str:
        return model_enum_str
    return "Unknown Model"


def parse_gen_metadata_blob(blob: bytes) -> Optional[Dict[str, Any]]:
    """解析 gen_metadata 表中存储的 Protobuf BLOB"""
    if not blob or not isinstance(blob, (bytes, bytearray)):
        return None

    root = parse_proto_message(bytes(blob))
    gen_uuid = get_first_str(root, 4)

    chat_model_raw = get_first_bytes(root, 1)
    if not chat_model_raw:
        return None

    chat_model = parse_proto_message(chat_model_raw)
    usage_raw = get_first_bytes(chat_model, 4)
    if not usage_raw:
        return None

    usage = parse_proto_message(usage_raw)

    input_tokens = get_first_varint(usage, 2, 0)
    total_output_field3 = get_first_varint(usage, 3, 0)
    cache_write_tokens = get_first_varint(usage, 4, 0)
    cache_read_tokens = get_first_varint(usage, 5, 0)
    thinking_tokens = get_first_varint(usage, 9, 0)
    response_tokens = get_first_varint(usage, 10, 0)
    response_id = get_first_str(usage, 11)

    if response_tokens == 0 and thinking_tokens == 0 and total_output_field3 > 0:
        response_tokens = total_output_field3
        total_output = total_output_field3
    else:
        total_output = max(total_output_field3, thinking_tokens + response_tokens)

    # 过滤无效全 0 记录
    if (input_tokens + cache_read_tokens + cache_write_tokens + total_output) == 0:
        return None

    model_name = resolve_model_name(chat_model, usage)

    return {
        "model": model_name,
        "input_tokens": input_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "thinking_tokens": thinking_tokens,
        "response_tokens": response_tokens,
        "total_output_tokens": total_output,
        "total_tokens": input_tokens + cache_read_tokens + cache_write_tokens + total_output,
        "response_id": response_id,
        "gen_uuid": gen_uuid,
        "step_id": gen_uuid,
    }


def extract_step_timing(metadata_bytes: bytes) -> Optional[Dict[str, float]]:
    """
    从 steps 表中的 metadata Protobuf 提取单步的纳秒级生命周期时间戳：
    - t_start: 步骤发起时间 (Field 1)
    - t_first: 首个流式 Token 响应时间 (Field 6)
    - t_end: 模型生成/步骤完成时间 (Field 7 或 Field 8)
    """
    if not metadata_bytes:
        return None
    try:
        fields = parse_proto_message(metadata_bytes)
        times = {}
        for fnum in (1, 6, 7, 8):
            if fnum in fields and fields[fnum]:
                sub = parse_proto_message(fields[fnum][0][1])
                sec = get_first_varint(sub, 1, 0)
                nanos = get_first_varint(sub, 2, 0)
                if sec > 1000000000:
                    times[fnum] = sec + nanos / 1e9

        if 1 in times:
            t_start = times[1]
            t_end = times.get(8, times.get(7, t_start))
            t_first = times.get(6, t_start)
            dur = max(0.0, t_end - t_start)
            ttft = max(0.0, t_first - t_start)
            return {
                "start": t_start,
                "first": t_first,
                "end": t_end,
                "duration": dur,
                "ttft": ttft
            }
    except Exception:
        pass
    return None


def read_conversation_db(db_path: Path) -> List[Dict[str, Any]]:
    """读取单个会话数据库中的所有有效 Token 轮次记录，附加高精度时间戳、耗时与生成速率"""
    records = []
    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=3.0)
    except Exception:
        try:
            conn = sqlite3.connect(str(db_path), timeout=3.0)
        except Exception:
            return records

    try:
        cur = conn.cursor()
        # 1. 检查是否存在 gen_metadata 表
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='gen_metadata'")
        if not cur.fetchone():
            return records

        # 2. 从 steps 表中提取每一步的精确时间戳与耗时（支持按 step_id 与 idx 双重索引）
        step_timings_by_id = {}
        step_timings_by_idx = {}
        try:
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='steps'")
            if cur.fetchone():
                cur.execute("SELECT idx, metadata FROM steps WHERE metadata IS NOT NULL")
                for s_idx, s_meta in cur.fetchall():
                    timing = extract_step_timing(s_meta)
                    if timing:
                        step_timings_by_idx[s_idx] = timing
                        try:
                            m_root = parse_proto_message(bytes(s_meta))
                            s_step_id = get_first_str(m_root, 12)
                            if s_step_id:
                                step_timings_by_id[s_step_id] = timing
                        except Exception:
                            pass
        except Exception:
            pass

        # 3. 动态探测列名
        cur.execute("PRAGMA table_info(gen_metadata)")
        cols = [row[1] for row in cur.fetchall()]
        blob_col = "data" if "data" in cols else cols[-1]
        idx_col = "idx" if "idx" in cols else "rowid"

        cur.execute(f"SELECT {idx_col}, {blob_col} FROM gen_metadata ORDER BY {idx_col} ASC")
        seen_resp_ids = set()

        file_mtime_sec = int(db_path.stat().st_mtime)

        for row_idx, blob in cur.fetchall():
            parsed = parse_gen_metadata_blob(blob)
            if not parsed:
                continue

            dedup_key = parsed["response_id"] or parsed["gen_uuid"] or f"idx_{row_idx}"
            if dedup_key in seen_resp_ids:
                continue
            seen_resp_ids.add(dedup_key)

            # 核心修复：优先通过 step_id (Field 12 / Field 4) 精确匹配步骤生命周期与时间戳
            step_id = parsed.get("step_id") or parsed.get("gen_uuid")
            timing = step_timings_by_id.get(step_id) if step_id else None
            if not timing:
                timing = step_timings_by_idx.get(row_idx)

            if timing:
                ts_sec = int(timing["start"])
                duration_sec = round(timing["duration"], 2)
                ttft_sec = round(timing["ttft"], 2)
                # 计算输出生成速度 (Output Tokens / sec: thinking + response)
                out_tok = parsed["total_output_tokens"]
                speed_tps = round(out_tok / duration_sec, 1) if duration_sec > 0.05 else 0.0
            else:
                ts_sec = file_mtime_sec
                duration_sec = 0.0
                ttft_sec = None
                speed_tps = 0.0

            dt = datetime.fromtimestamp(ts_sec)

            parsed["turn_idx"] = row_idx
            parsed["timestamp_sec"] = ts_sec
            parsed["timestamp_str"] = dt.strftime("%Y-%m-%d %H:%M:%S")
            parsed["date_str"] = dt.strftime("%Y-%m-%d")
            parsed["hour_str"] = dt.strftime("%Y-%m-%d %H:00")
            parsed["hour_num"] = dt.hour
            parsed["duration_sec"] = duration_sec
            parsed["ttft_sec"] = ttft_sec
            parsed["speed_tps"] = speed_tps

            records.append(parsed)
    except Exception:
        pass
    finally:
        conn.close()

    return records
