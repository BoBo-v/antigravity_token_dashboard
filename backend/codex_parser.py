"""Codex JSONL / zstd usage parser with disjoint token categories."""

import hashlib
import io
import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Any

from .usage import local_timestamp, token_count

try:
    import zstandard as zstd
except ImportError:
    zstd = None
HAS_ZSTD = zstd is not None
READ_ERRORS = (OSError, UnicodeError) + ((zstd.ZstdError,) if zstd else ())


def read_codex_session(file_path: Path, titles_map: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    if not file_path.is_file():
        return []
    is_zst = file_path.name.endswith(".zst")
    if is_zst and not HAS_ZSTD:
        return []
    records = []
    fallback = file_path.stat().st_mtime
    session_id = None
    title = ""
    model = "Unknown Model"
    previous = None
    seen = set()
    fields = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens",
              "output_tokens", "reasoning_output_tokens", "total_tokens")

    def parse_stream(stream):
        nonlocal session_id, title, model, previous
        for line in stream:
            try:
                obj = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(obj, dict):
                continue
            payload = obj.get("payload")
            if not isinstance(payload, dict):
                continue
            kind = obj.get("type")
            if kind == "session_meta":
                session_id = payload.get("session_id") or payload.get("id") or session_id
                model = payload.get("model") or model
            elif kind == "turn_context":
                model = payload.get("model") or model
            elif kind == "response_item" and payload.get("role") == "user" and not title:
                for part in payload.get("content", []) or []:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        text = part["text"]
                        if not text.startswith("<environment_context>"):
                            title = text[:60].strip()
                            break
            elif payload.get("type") == "token_count":
                info = payload.get("info")
                if not isinstance(info, dict):
                    continue
                cumulative = info.get("total_token_usage")
                last = info.get("last_token_usage")
                cumulative = cumulative if isinstance(cumulative, dict) else {}
                last = last if isinstance(last, dict) else {}
                total = token_count(cumulative.get("total_tokens"))
                if previous and total == previous["total_tokens"] and total > 0:
                    continue
                usage = {key: token_count(last.get(key)) for key in fields}
                aggregated = False
                if total:
                    current = {key: token_count(cumulative.get(key)) for key in fields}
                    # A fork can start with an inherited cumulative counter.
                    # Subtract only after observing a baseline in this file.
                    if previous and total > previous["total_tokens"]:
                        delta = {key: max(0, current[key] - previous[key]) for key in fields}
                        if delta["total_tokens"] != usage["total_tokens"]:
                            usage = delta
                            aggregated = True
                    elif not last:
                        usage = current
                        aggregated = True
                    previous = current
                inclusive_input = usage["input_tokens"]
                cache_read = min(inclusive_input, usage["cached_input_tokens"])
                cache_write = min(inclusive_input - cache_read, usage["cache_write_input_tokens"])
                output = usage["output_tokens"]
                thinking = min(output, usage["reasoning_output_tokens"])
                if inclusive_input + output == 0:
                    continue
                fingerprint = json.dumps([obj.get("timestamp"), total, usage], sort_keys=True)
                key = hashlib.sha256(fingerprint.encode()).hexdigest()[:24]
                if key in seen:
                    continue
                seen.add(key)
                records.append({
                    "turn_idx": len(records) + 1, "model": model,
                    "input_tokens": inclusive_input - cache_read - cache_write,
                    "cache_read_tokens": cache_read, "cache_write_tokens": cache_write,
                    "thinking_tokens": thinking, "response_tokens": output - thinking,
                    "total_output_tokens": output, "total_tokens": inclusive_input + output,
                    "response_id": f"codex_{key}", "gen_uuid": f"codex_{key}",
                    "usage_aggregated": aggregated,
                    **local_timestamp(obj.get("timestamp"), fallback),
                    "duration_sec": 0.0, "ttft_sec": None, "speed_tps": 0.0,
                    "source_app": "codex",
                })

    try:
        if is_zst:
            with file_path.open("rb") as file:
                with zstd.ZstdDecompressor().stream_reader(file) as reader:
                    with io.TextIOWrapper(reader, encoding="utf-8", errors="replace") as stream:
                        parse_stream(stream)
        else:
            with file_path.open(encoding="utf-8", errors="replace") as stream:
                parse_stream(stream)
    except READ_ERRORS as error:
        logging.getLogger(__name__).warning("Cannot read Codex log %s: %s", file_path, error)
    if not session_id:
        match = re.search(r"([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})(?:\.jsonl(?:\.zst)?)?$", file_path.name, re.I)
        session_id = match.group(1) if match else file_path.name.removesuffix(".zst").removesuffix(".jsonl")
    title = (titles_map or {}).get(session_id) or title or session_id[:16]
    for record in records:
        record.update(session_id=session_id, session_title=title)
    return records
