"""Process-local Tray quota guard.

Official Tray limits are 180 req/min and 10k/day (50k corporate). With two
Render instances, default to 90/min and 4000/day per process.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any

from .exceptions import TrayAPIError

logger = logging.getLogger(__name__)

_lock = threading.Lock()


class _Window:
    def __init__(self) -> None:
        self.minute: deque[float] = deque()
        self.day: deque[float] = deque()
        self.warned_minute = False
        self.warned_day = False


_windows: dict[str, _Window] = {}


def reset_tray_rate_limiter_for_tests() -> None:
    with _lock:
        _windows.clear()


def _window(store_id: str) -> _Window:
    window = _windows.get(store_id)
    if window is None:
        window = _Window()
        _windows[store_id] = window
    return window


def acquire_tray_quota(settings: Any | None = None) -> None:
    per_minute = int(getattr(settings, "tray_rate_limit_per_minute", 90) or 0)
    per_day = int(getattr(settings, "tray_rate_limit_per_day", 4000) or 0)
    if per_minute <= 0 and per_day <= 0:
        return

    store_id = str(getattr(settings, "tray_store_code", "") or "")
    now = time.time()
    with _lock:
        window = _window(store_id)
        while window.minute and now - window.minute[0] > 60:
            window.minute.popleft()
        while window.day and now - window.day[0] > 86400:
            window.day.popleft()

        minute_count = len(window.minute)
        day_count = len(window.day)
        if per_minute > 0 and minute_count >= per_minute:
            raise TrayAPIError(
                "Tray rate limit exceeded",
                429,
                diagnostics={
                    "error_code": "tray_rate_limited",
                    "error_type": "rate_limit",
                    "error_message": "minute quota exceeded",
                },
            )
        if per_day > 0 and day_count >= per_day:
            raise TrayAPIError(
                "Tray daily rate limit exceeded",
                429,
                diagnostics={
                    "error_code": "tray_rate_limited",
                    "error_type": "rate_limit",
                    "error_message": "daily quota exceeded",
                },
            )

        window.minute.append(now)
        window.day.append(now)
        minute_count += 1
        day_count += 1

        if per_minute > 0 and minute_count >= int(per_minute * 0.8):
            if not window.warned_minute:
                logger.warning(
                    "Tray per-minute quota at %s/%s on this instance for store %s",
                    minute_count,
                    per_minute,
                    store_id or "default",
                )
                window.warned_minute = True
        else:
            window.warned_minute = False

        if per_day > 0 and day_count >= int(per_day * 0.8):
            if not window.warned_day:
                logger.warning(
                    "Tray per-day quota at %s/%s on this instance for store %s",
                    day_count,
                    per_day,
                    store_id or "default",
                )
                window.warned_day = True
        else:
            window.warned_day = False
