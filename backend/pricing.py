"""Explicit, per-source/model reference prices; unknown prices stay unknown."""

import math

RATE_FIELDS = ("input", "cache_read", "cache_write", "output")


def validate_pricing(config):
    if not isinstance(config, dict) or not isinstance(config.get("models", {}), dict):
        raise ValueError("价格配置必须包含 models 对象")
    exchange = config.get("exchange_rate", 7.23)
    if isinstance(exchange, bool) or not isinstance(exchange, (int, float)) or not math.isfinite(exchange) or exchange <= 0:
        raise ValueError("汇率必须为正数")
    models = {}
    for key, rates in config.get("models", {}).items():
        if not isinstance(key, str) or ":" not in key or not isinstance(rates, dict):
            raise ValueError("模型价格格式错误")
        clean = {}
        for name in RATE_FIELDS:
            rate = rates.get(name)
            if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not math.isfinite(rate) or rate < 0:
                raise ValueError(f"{key}: {name} 单价必须为非负数，单位 USD / 百万 Token")
            clean[name] = float(rate)
        models[key] = clean
    return {"exchange_rate": float(exchange), "models": models}


def calculate_costs(turns, config=None):
    config = config or {"models": {}, "exchange_rate": 7.23}
    totals = {name: 0.0 for name in ("input_usd", "cache_usd", "cache_write_usd", "output_usd", "saved_usd")}
    unpriced = set()
    priced_count = 0
    for turn in turns:
        key = f"{turn.get('source_app', 'antigravity')}:{turn['model']}"
        rates = config.get("models", {}).get(key)
        if rates is None:
            unpriced.add(key)
            continue
        priced_count += 1
        totals["input_usd"] += turn["input_tokens"] * rates["input"] / 1e6
        totals["cache_usd"] += turn["cache_read_tokens"] * rates["cache_read"] / 1e6
        totals["cache_write_usd"] += turn.get("cache_write_tokens", 0) * rates["cache_write"] / 1e6
        totals["output_usd"] += turn["total_output_tokens"] * rates["output"] / 1e6
        totals["saved_usd"] += turn["cache_read_tokens"] * max(0, rates["input"] - rates["cache_read"]) / 1e6
    known = priced_count > 0 or not turns
    total = sum(totals[name] for name in ("input_usd", "cache_usd", "cache_write_usd", "output_usd"))
    exchange = config.get("exchange_rate", 7.23)
    values = {name: round(value, 8) if known else None for name, value in totals.items()}
    values.update(
        total_usd=round(total, 8) if known else None,
        total_cny=round(total * exchange, 8) if known else None,
        saved_cny=round(totals["saved_usd"] * exchange, 8) if known else None,
        saved_percent=round(totals["saved_usd"] / (total + totals["saved_usd"]) * 100, 2)
        if total + totals["saved_usd"] > 0 else 0,
    )
    return {
        "exchange_rate": exchange, "configured": values,
        # Retain response keys for older clients, without inventing price tiers.
        "promo": values, "standard": values,
        "priced_turns": priced_count, "unpriced_turns": len(turns) - priced_count,
        "unpriced_models": sorted(unpriced), "complete": not unpriced,
    }
