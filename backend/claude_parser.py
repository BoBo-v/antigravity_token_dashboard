"""Claude Code logs repeat message usage for each streamed content block."""

import json
from pathlib import Path
from typing import Dict, List, Optional, Any

from .usage import local_timestamp, token_count


def read_claude_session(jsonl_path: Path, titles_map: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    if not jsonl_path.is_file():
        return []
    fallback = jsonl_path.stat().st_mtime
    sid = jsonl_path.stem
    title = ""
    messages = {}
    token_fields = {
        "input_tokens": "input_tokens", "cache_read_tokens": "cache_read_input_tokens",
        "cache_write_tokens": "cache_creation_input_tokens", "response_tokens": "output_tokens",
    }
    try:
        with jsonl_path.open(encoding="utf-8", errors="replace") as stream:
            for line_number, line in enumerate(stream):
                try:
                    obj = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if not isinstance(obj, dict) or not isinstance(obj.get("message"), dict):
                    continue
                msg = obj["message"]
                if obj.get("type") == "user" and not title:
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        title = content[:60].strip()
                    elif isinstance(content, list):
                        title = next((part["text"][:60].strip() for part in content
                                      if isinstance(part, dict) and isinstance(part.get("text"), str)), "")
                if obj.get("type") != "assistant" or msg.get("model") == "<synthetic>":
                    continue
                usage = msg.get("usage")
                if not isinstance(usage, dict):
                    continue
                counts = {dest: token_count(usage.get(src)) for dest, src in token_fields.items()}
                if not sum(counts.values()):
                    continue
                message_id = msg.get("id") or obj.get("uuid") or f"line_{line_number}"
                model = msg.get("model") or "Unknown Model"
                key = (model, message_id)
                if key in messages:
                    record = messages[key]
                    for name, value in counts.items():
                        record[name] = max(record[name], value)
                else:
                    record = {
                        "turn_idx": len(messages) + 1, "model": model, **counts,
                        "thinking_tokens": 0, "response_id": message_id,
                        "gen_uuid": f"claude_{message_id}",
                        **local_timestamp(obj.get("timestamp"), fallback),
                        "duration_sec": 0.0, "ttft_sec": None, "speed_tps": 0.0,
                        "source_app": "claude-code", "session_id": sid,
                    }
                    messages[key] = record
                record["total_output_tokens"] = record["response_tokens"]
                record["total_tokens"] = sum(record[field] for field in token_fields)
    except OSError:
        pass
    title = (titles_map or {}).get(sid) or title or sid[:16]
    for record in messages.values():
        record["session_title"] = title
    return list(messages.values())
