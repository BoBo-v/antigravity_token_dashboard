"""Shared normalization for local usage logs."""

from datetime import datetime


def token_count(value):
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def local_timestamp(raw, fallback):
    """Use the event's instant, then derive display and grouping fields locally."""
    try:
        instant = datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except (AttributeError, TypeError, ValueError, OverflowError):
        instant = fallback
    dt = datetime.fromtimestamp(instant)
    return {
        "timestamp_sec": int(instant),
        "timestamp_str": dt.strftime("%Y-%m-%d %H:%M:%S"),
        "date_str": dt.strftime("%Y-%m-%d"),
        "hour_str": dt.strftime("%Y-%m-%d %H:00"),
        "hour_num": dt.hour,
    }
