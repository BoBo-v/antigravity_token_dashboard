#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FastAPI 后端服务入口与 REST API 接口定义
"""

import os
import sys
import json
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query, Response, Body, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .scanner import scanner_service
from .pricing import validate_pricing

app = FastAPI(title="Antigravity Token Dashboard", version="1.0.0")

# 开启跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_static_dir() -> Path:
    """获取静态资源根目录（兼容 PyInstaller 打包与源码开发运行）"""
    if hasattr(sys, "_MEIPASS"):
        p = Path(sys._MEIPASS) / "static"
        if p.exists():
            return p
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        for candidate in [exe_dir / "static", exe_dir / "_internal" / "static"]:
            if candidate.exists():
                return candidate
    return Path(__file__).resolve().parent.parent / "static"


def get_config_file() -> Path:
    """获取持久化配置路径（打包后优先存放在 exe 同级 data/ 目录或 %APPDATA%）"""
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        data_dir = exe_dir / "data"
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
            return data_dir / "quota_config.json"
        except (PermissionError, OSError):
            appdata = Path(os.environ.get("APPDATA", Path.home())) / "AntigravityTokenDashboard" / "data"
            appdata.mkdir(parents=True, exist_ok=True)
            return appdata / "quota_config.json"
    return Path(__file__).resolve().parent.parent / "data" / "quota_config.json"


STATIC_DIR = get_static_dir()
CONFIG_FILE = get_config_file()


def load_quota_config() -> dict:
    cfg_file = get_config_file()
    if cfg_file.exists():
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    # No calibration exists until a user actually provides one.
    return {
        name: {"remaining_pct": None, "reset_seconds": 0, "reset_time_str": "", "calibrated_at": 0}
        for name in ("quota_5h", "quota_week")
    }


def load_pricing_config():
    path = get_config_file().with_name("pricing_config.json")
    try:
        return validate_pricing(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return {"exchange_rate": 7.23, "models": {}}


@app.get("/api/pricing-config")
def get_pricing_config():
    turns = scanner_service.get_all_turns()
    observed = sorted({(t.get("source_app", "antigravity"), t["model"]) for t in turns})
    return {"success": True, "config": load_pricing_config(),
            "models": [{"source_app": source, "model": model, "key": f"{source}:{model}"}
                       for source, model in observed]}


@app.post("/api/pricing-config")
def save_pricing_config(cfg: dict = Body(...)):
    try:
        cfg = validate_pricing(cfg)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    path = get_config_file().with_name("pricing_config.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    scanner_service.pricing_config = cfg
    return {"success": True, "config": cfg}


@app.on_event("startup")
def on_startup():
    """服务启动时预热扫描本地数据库"""
    scanner_service.scan()


@app.get("/api/overview")
def get_overview(
    response: Response,
    range: str = "today",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    source: Optional[str] = "all",
    force_scan: bool = False,
):
    """获取指定时间范围与工具来源下的统计指标卡片、时序走势图及模型占比数据"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    all_turns = scanner_service.get_all_turns(force_scan=force_scan)
    filtered = scanner_service.filter_turns(all_turns, time_range=range, start_date=start_date, end_date=end_date, source=source)

    scanner_service.pricing_config = load_pricing_config()
    summary = scanner_service.calculate_summary(filtered)
    trend = scanner_service.calculate_trend(filtered, time_range=range)
    models = scanner_service.calculate_models(filtered)
    custom_quota = load_quota_config()
    official_quotas = scanner_service.get_official_usage_snapshot()
    quotas = scanner_service.calculate_quotas(all_turns, custom_quota=custom_quota, source=source)

    return {
        "success": True,
        "range": range,
        "source": source or "all",
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
    for name in ("quota_5h", "quota_week"):
        value = cfg.get(name, {})
        if not isinstance(value, dict):
            raise HTTPException(422, "配额格式错误")
        pct = value.get("remaining_pct")
        seconds = value.get("reset_seconds", 0)
        if pct is not None and (isinstance(pct, bool) or not isinstance(pct, (int, float)) or not 0 <= pct <= 100):
            raise HTTPException(422, "剩余百分比必须在 0 到 100 之间")
        if isinstance(seconds, bool) or not isinstance(seconds, int) or not 0 <= seconds <= 366 * 86400:
            raise HTTPException(422, "重置秒数格式错误")
    cfg_file = get_config_file()
    cfg_file.parent.mkdir(parents=True, exist_ok=True)
    now_ts = int(time.time())
    if "calibrated_at" not in cfg:
        cfg["calibrated_at"] = now_ts
    if "quota_5h" in cfg and isinstance(cfg["quota_5h"], dict):
        cfg["quota_5h"].setdefault("calibrated_at", now_ts)
    if "quota_week" in cfg and isinstance(cfg["quota_week"], dict):
        cfg["quota_week"].setdefault("calibrated_at", now_ts)
    with open(cfg_file, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return {"success": True, "data": cfg}


@app.get("/api/official-usage")
def get_official_usage(force: bool = False):
    """直接执行本地 agy.exe -p /usage --output-format json 获取官方云端订阅配额（可选）"""
    return scanner_service.fetch_official_agy_usage(force=force)


@app.get("/api/sessions")
def get_sessions(
    response: Response,
    range: str = "today",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    source: Optional[str] = "all",
    page: int = 1,
    page_size: int = 15,
    search: str = "",
):
    """获取指定时间范围与工具来源下的会话明细列表（支持分页、搜索与多工具）"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    all_turns = scanner_service.get_all_turns()
    filtered = scanner_service.filter_turns(all_turns, time_range=range, start_date=start_date, end_date=end_date, source=source)
    scanner_service.pricing_config = load_pricing_config()
    result = scanner_service.get_sessions_table(filtered, page=page, page_size=page_size, search=search, source=source)
    return {
        "success": True,
        "data": result
    }


@app.post("/api/refresh")
def refresh_data(response: Response):
    """手动重新扫描本地所有数据库（Antigravity、Codex、Claude Code），更新内存缓存"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    t0 = time.time()
    scanner_service.scan(force=True)
    cost_ms = round((time.time() - t0) * 1000, 1)
    all_turns = scanner_service.get_all_turns()
    return {
        "success": True,
        "message": f"刷新成功，已扫描 {scanner_service.total_db_count} 个会话源文件，共解析 {len(all_turns)} 条轮次，耗时 {cost_ms}ms",
        "cost_ms": cost_ms,
        "last_scan_time": scanner_service.last_scan_time.strftime("%Y-%m-%d %H:%M:%S") if scanner_service.last_scan_time else "",
    }


@app.get("/api/export-csv")
def export_csv(
    range: str = Query("today"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    source: Optional[str] = Query("all"),
):
    """导出当前筛选结果为带 UTF-8 BOM 的 CSV 报表"""
    all_turns = scanner_service.get_all_turns()
    filtered = scanner_service.filter_turns(all_turns, time_range=range, start_date=start_date, end_date=end_date, source=source)
    scanner_service.pricing_config = load_pricing_config()
    csv_content = scanner_service.generate_csv_report(filtered)

    filename = f"multi_agent_tokens_{range}_{int(time.time())}.csv"
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
