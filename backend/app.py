#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FastAPI 后端服务入口与 REST API 接口定义
"""

import os
import json
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query, Response, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .scanner import scanner_service

app = FastAPI(title="Antigravity Token Dashboard", version="1.0.0")

# 开启跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态资源与配置路径
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
CONFIG_FILE = Path(__file__).resolve().parent.parent / "data" / "quota_config.json"


def load_quota_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    # 默认值
    now_ts = int(time.time())
    return {
        "quota_5h": {
            "remaining_pct": 95,
            "reset_seconds": 16000,
            "reset_time_str": "4小时28分",
            "capacity_tokens": 10000000,
            "calibrated_at": now_ts,
        },
        "quota_week": {
            "remaining_pct": 88,
            "reset_seconds": 580000,
            "reset_time_str": "6天18小时",
            "capacity_tokens": 50000000,
            "calibrated_at": now_ts,
        }
    }


@app.on_event("startup")
def on_startup():
    """服务启动时预热扫描本地数据库"""
    scanner_service.scan()


@app.get("/api/overview")
def get_overview(
    range: str = "today",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    """获取指定时间范围内的统计指标卡片、时序走势图及模型占比数据"""
    all_turns = scanner_service.get_all_turns()
    filtered = scanner_service.filter_turns(all_turns, time_range=range, start_date=start_date, end_date=end_date)

    summary = scanner_service.calculate_summary(filtered)
    trend = scanner_service.calculate_trend(filtered, time_range=range)
    models = scanner_service.calculate_models(filtered)
    quotas = scanner_service.calculate_quotas(all_turns)
    custom_quota = load_quota_config()
    official_quotas = scanner_service._official_usage_cache

    return {
        "success": True,
        "range": range,
        "meta": {
            "last_scan_time": scanner_service.last_scan_time.strftime("%Y-%m-%d %H:%M:%S") if scanner_service.last_scan_time else "",
            "total_dbs": scanner_service.total_db_count,
            "total_all_turns": len(all_turns),
            "matched_turns": len(filtered),
        },
        "summary": summary,
        "trend": trend,
        "models": models,
        "quotas": quotas,
        "custom_quota": custom_quota,
        "official_quotas": official_quotas,
    }


@app.get("/api/quota-config")
def get_quota_config():
    """获取用户手动设置的配额配置（5H剩余、重置时间、周限额等）"""
    cfg = load_quota_config()
    return {
        "success": True,
        "config": cfg,
        **cfg
    }


@app.post("/api/quota-config")
def save_quota_config(cfg: dict = Body(...)):
    """保存用户手动设置的配额配置"""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    cfg["calibrated_at"] = int(time.time())
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return {"success": True, "data": cfg}


@app.get("/api/official-usage")
def get_official_usage(force: bool = False):
    """直接执行本地 agy.exe -p /usage --output-format json 获取官方云端订阅配额（可选）"""
    return scanner_service.fetch_official_agy_usage(force=force)


@app.get("/api/sessions")
def get_sessions(
    range: str = "today",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    page: int = 1,
    page_size: int = 15,
    search: str = "",
):
    """获取指定时间范围下的会话明细列表（支持分页与搜索）"""
    all_turns = scanner_service.get_all_turns()
    filtered = scanner_service.filter_turns(all_turns, time_range=range, start_date=start_date, end_date=end_date)
    result = scanner_service.get_sessions_table(filtered, page=page, page_size=page_size, search=search)
    return {
        "success": True,
        "data": result
    }


@app.post("/api/refresh")
def refresh_data():
    """手动重新扫描本地所有数据库，更新内存缓存"""
    t0 = time.time()
    scanner_service.scan(force=True)
    cost_ms = round((time.time() - t0) * 1000, 1)
    all_turns = scanner_service.get_all_turns()
    return {
        "success": True,
        "message": f"刷新成功，扫描 {scanner_service.total_db_count} 个数据库，共 {len(all_turns)} 条轮次，耗时 {cost_ms}ms",
        "cost_ms": cost_ms,
        "last_scan_time": scanner_service.last_scan_time.strftime("%Y-%m-%d %H:%M:%S") if scanner_service.last_scan_time else "",
    }


@app.get("/api/export-csv")
def export_csv(
    range: str = Query("today"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    """导出当前筛选结果为带 UTF-8 BOM 的 CSV 报表"""
    all_turns = scanner_service.get_all_turns()
    filtered = scanner_service.filter_turns(all_turns, time_range=range, start_date=start_date, end_date=end_date)
    csv_content = scanner_service.generate_csv_report(filtered)

    filename = f"antigravity_tokens_{range}_{int(time.time())}.csv"
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


# 挂载静态页面
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    def serve_index():
        return FileResponse(STATIC_DIR / "index.html")
