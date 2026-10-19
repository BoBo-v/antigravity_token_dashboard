"""Regression cases for real log patterns and accounting boundaries."""

import csv
import io
import json
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.claude_parser import read_claude_session
from backend.codex_parser import read_codex_session
from backend.pricing import calculate_costs, validate_pricing
from backend.scanner import TokenScannerService


def varint(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def number(field, value):
    return varint(field << 3) + varint(value)


def message(field, value):
    if isinstance(value, str):
        value = value.encode()
    return varint((field << 3) | 2) + varint(len(value)) + value


def metadata(response):
    usage = number(2, 100) + number(3, 7) + number(5, 20) + message(11, response)
    return message(1, message(4, usage)) + message(4, response)


def turn(source="codex", model="test", timestamp=None, **overrides):
    result = dict(session_id="session", session_title="test", source_app=source, model=model,
                  turn_idx=1, response_id="response", timestamp_sec=timestamp or int(time.time()) - 30,
                  input_tokens=100, cache_read_tokens=80, cache_write_tokens=20,
                  total_output_tokens=50, thinking_tokens=10, response_tokens=40,
                  total_tokens=250, duration_sec=0, speed_tps=0)
    result.update(overrides)
    return result


class UsageAccuracyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dashboard-accuracy-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.scanner = TokenScannerService(str(self.root / "gemini"))
        (self.root / "gemini").mkdir()
        self.scanner.get_codex_root = lambda: self.root / "codex"
        self.scanner.get_claude_root = lambda: self.root / "claude"

    def write_log(self, name, lines):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")
        return path

    def codex_event(self, cumulative, last=None, timestamp="2026-10-19T00:30:00Z"):
        return {"type": "event_msg", "timestamp": timestamp, "payload": {"type": "token_count", "info": {
            "total_token_usage": cumulative, "last_token_usage": last if last is not None else cumulative}}}

    def test_codex_cache_is_input_subset_and_thinking_is_output_subset(self):
        usage = dict(input_tokens=1000, cached_input_tokens=800, cache_write_input_tokens=50,
                     output_tokens=150, reasoning_output_tokens=50, total_tokens=1150)
        event = self.codex_event(usage)
        records = read_codex_session(self.write_log("codex.jsonl", [None, {"payload": None}, event, event]))
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["input_tokens"], 150)
        self.assertEqual(record["response_tokens"], 100)
        self.assertEqual(sum(record[key] for key in ("input_tokens", "cache_read_tokens", "cache_write_tokens", "total_output_tokens")), 1150)

    def test_codex_recovers_gaps_and_counter_resets(self):
        first = dict(input_tokens=100, output_tokens=10, total_tokens=110)
        total = dict(input_tokens=400, output_tokens=40, total_tokens=440)
        last = dict(input_tokens=200, output_tokens=20, total_tokens=220)
        records = read_codex_session(self.write_log("gap.jsonl", [self.codex_event(first),
            self.codex_event(total, last, "2026-10-19T00:31:00Z"),
            self.codex_event(first, timestamp="2026-10-19T00:32:00Z")]))
        self.assertEqual([r["total_tokens"] for r in records], [110, 330, 110])
        self.assertTrue(records[1]["usage_aggregated"])

    def test_codex_does_not_count_inherited_initial_counter(self):
        last = dict(input_tokens=100, output_tokens=10, total_tokens=110)
        records = read_codex_session(self.write_log("fork.jsonl", [self.codex_event(
            dict(input_tokens=10000, output_tokens=1000, total_tokens=11000), last)]))
        self.assertEqual(records[0]["total_tokens"], 110)

    def test_claude_content_blocks_merge_maximum_usage(self):
        def assistant(output):
            return {"type": "assistant", "timestamp": "2026-10-19T00:30:00Z", "message": {
                "id": "msg-1", "model": "claude-test", "usage": {
                    "input_tokens": 10, "cache_read_input_tokens": 100,
                    "cache_creation_input_tokens": 50, "output_tokens": output}}}
        records = read_claude_session(self.write_log("claude.jsonl", [assistant(5), assistant(5), assistant(20), assistant(4)]))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["total_tokens"], 180)
        self.assertEqual(records[0]["response_tokens"], 20)

    def test_both_parsers_group_cross_midnight_in_local_timezone(self):
        local = datetime(2026, 10, 19, 0, 15)
        raw = local.astimezone(timezone.utc).isoformat()
        usage = dict(input_tokens=10, output_tokens=1, total_tokens=11)
        codex = read_codex_session(self.write_log("time.jsonl", [self.codex_event(usage, timestamp=raw)]))[0]
        claude = read_claude_session(self.write_log("ctime.jsonl", [{"type": "assistant", "timestamp": raw,
            "message": {"id": "time", "model": "test", "usage": {"input_tokens": 10, "output_tokens": 1}}}]))[0]
        for record in (codex, claude):
            self.assertEqual(record["date_str"], "2026-10-19")
            self.assertEqual(record["hour_num"], 0)
            self.assertEqual(record["timestamp_sec"], int(local.timestamp()))

    def test_archive_and_active_copies_merge_records_instead_of_dropping_sessions(self):
        first = dict(input_tokens=100, output_tokens=10, total_tokens=110)
        second = dict(input_tokens=200, output_tokens=20, total_tokens=220)
        meta = {"type": "session_meta", "payload": {"id": "same-session"}}
        self.write_log("codex/sessions/copy.jsonl", [meta, self.codex_event(first)])
        self.write_log("codex/archived_sessions/copy.jsonl", [meta, self.codex_event(first), self.codex_event(second, first)])
        turns = self.scanner.get_all_turns()
        self.assertEqual(self.scanner.total_db_count, 2)
        self.assertEqual(len(turns), 2)
        self.assertEqual(sum(t["total_tokens"] for t in turns), 220)

    def test_zstd_logs_are_read(self):
        import zstandard
        event = self.codex_event(dict(input_tokens=100, output_tokens=10, total_tokens=110))
        path = self.root / "compressed.jsonl.zst"
        path.write_bytes(zstandard.ZstdCompressor().compress(json.dumps(event).encode()))
        self.assertEqual(read_codex_session(path)[0]["total_tokens"], 110)

    def test_wal_commits_refresh_without_main_database_mtime_change(self):
        path = self.root / "gemini" / "session.db"
        writer = sqlite3.connect(path)
        try:
            writer.execute("pragma journal_mode=wal")
            writer.execute("pragma wal_autocheckpoint=0")
            writer.execute("create table gen_metadata(idx integer, data blob)")
            writer.execute("insert into gen_metadata values(1, ?)", (metadata("one"),))
            writer.commit()
            writer.execute("pragma wal_checkpoint(truncate)")
            self.assertEqual(len(self.scanner.get_all_turns()), 1)
            mtime = path.stat().st_mtime_ns
            writer.execute("insert into gen_metadata values(2, ?)", (metadata("two"),))
            writer.commit()
            self.assertEqual(path.stat().st_mtime_ns, mtime)
            self.scanner.scan()
            self.assertEqual(len(self.scanner.get_all_turns(max_cache_age=100)), 2)
        finally:
            writer.close()

    def test_source_filter_and_exact_first_expiry_batch(self):
        now = int(time.time())
        turns = [turn(timestamp=now-100), turn(timestamp=now-100), turn(timestamp=now-90),
                 turn(source="antigravity", timestamp=now-110), turn(timestamp=now+500)]
        quota = self.scanner.calculate_quotas(turns, source="codex")
        self.assertEqual(quota["quota_5h"]["used_tokens"], 750)
        self.assertEqual(quota["quota_5h"]["next_relief_tokens"], 500)
        self.assertEqual(quota["quota_5h"]["input_tokens"], 600)

    def test_manual_calibration_is_preserved_even_at_zero(self):
        now = int(time.time())
        for percentage in (0, 80):
            config = {"quota_5h": {"remaining_pct": percentage, "capacity_tokens": 10000000,
                                   "calibrated_at": now, "reset_seconds": 3600}}
            quota = self.scanner.calculate_quotas([turn()], config, {"success": True, "groups": []})
            self.assertEqual(quota["quota_5h"]["snapshot"]["remaining_pct"], percentage)
            self.assertIsNone(quota["quota_5h"]["dynamic"])
        self.assertIsNone(self.scanner.calculate_quotas([])["quota_5h"]["snapshot"]["remaining_pct"])

    def test_expired_snapshot_becomes_unknown_not_full(self):
        quota = self.scanner.calculate_quotas([], {"quota_5h": {
            "remaining_pct": 70, "calibrated_at": int(time.time()) - 4000, "reset_seconds": 3600}})
        self.assertIsNone(quota["quota_5h"]["snapshot"]["remaining_pct"])
        self.assertTrue(quota["quota_5h"]["snapshot"]["expired"])

    def test_per_model_prices_include_writes_and_match_csv_and_sessions(self):
        config = validate_pricing({"models": {
            "codex:one": dict(input=2, cache_read=0.2, cache_write=3, output=10),
            "codex:two": dict(input=4, cache_read=0.4, cache_write=6, output=20)}})
        self.scanner.pricing_config = config
        turns = [turn(model="one"), turn(model="two", turn_idx=2)]
        summary = self.scanner.calculate_summary(turns)
        self.assertAlmostEqual(summary["costs"]["configured"]["total_usd"], 0.002328)
        self.assertAlmostEqual(summary["costs"]["configured"]["cache_write_usd"], 0.00018)
        session = self.scanner.get_sessions_table(turns)["items"][0]
        self.assertAlmostEqual(session["cost_usd"], summary["costs"]["configured"]["total_usd"])
        csv_rows = list(csv.DictReader(io.StringIO(self.scanner.generate_csv_report(turns).lstrip('\ufeff'))))
        self.assertAlmostEqual(sum(float(row["cost_promo_usd"]) for row in csv_rows), session["cost_usd"])
        self.assertTrue(all(row["pricing_status"] == "configured" for row in csv_rows))
        self.assertNotIn("cost_usd", turns[0], "rendering sessions must not mutate cached records")

    def test_unknown_prices_are_not_free_and_free_prices_are_valid(self):
        turns = [turn()]
        costs = calculate_costs(turns)
        self.assertIsNone(costs["configured"]["total_usd"])
        self.assertEqual(costs["unpriced_turns"], 1)
        costs = calculate_costs(turns, validate_pricing({"models": {"codex:test": dict.fromkeys(("input", "cache_read", "cache_write", "output"), 0)}}))
        self.assertEqual(costs["configured"]["total_usd"], 0)
        self.assertTrue(costs["complete"])

    def test_invalid_prices_are_rejected(self):
        for invalid in (-1, float('nan'), float('inf'), True, None):
            with self.assertRaises(ValueError):
                validate_pricing({"models": {"codex:test": dict(input=invalid, cache_read=0, cache_write=0, output=0)}})

    def test_official_reset_time_survives_and_failures_mark_old_snapshot_stale(self):
        payload = {"command": {"data": {"groups": [{"name": "Gemini", "buckets": [{
            "id": "gemini-weekly", "window": "weekly", "remaining_fraction": 0,
            "reset_time": "2026-10-24T05:19:35Z"}]}]}}}
        with patch("shutil.which", return_value="agy"), patch("subprocess.run", return_value=SimpleNamespace(
                returncode=0, stdout=json.dumps(payload), stderr="")):
            result = self.scanner.fetch_official_agy_usage(True)
        bucket = result["groups"][0]["buckets"][0]
        self.assertEqual(bucket["remaining_pct"], 0)
        self.assertEqual(bucket["reset_time"], "2026-10-24T05:19:35Z")
        with patch("shutil.which", return_value="agy"), patch("subprocess.run", side_effect=TimeoutError("timeout")):
            self.assertFalse(self.scanner.fetch_official_agy_usage(True)["success"])
        self.assertTrue(self.scanner.get_official_usage_snapshot()["stale"])

    def test_missing_official_fraction_is_not_assumed_full(self):
        payload = {"command": {"data": {"groups": [{"buckets": [{"window": "5h"}]}]}}}
        with patch("shutil.which", return_value="agy"), patch("subprocess.run", return_value=SimpleNamespace(
                returncode=0, stdout=json.dumps(payload), stderr="")):
            self.assertFalse(self.scanner.fetch_official_agy_usage(True)["success"])


if __name__ == "__main__":
    unittest.main()
