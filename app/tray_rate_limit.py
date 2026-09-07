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
_minute_events: deque[float] = deque()
_day_events: deque[float] = deque()
_warned_minute = False
_warned_day = False


def reset_tray_rate_limiter_for_tests() -> None:
    global _warned_minute, _warned_day
    with _lock:
        _minute_events.clear()
        _day_events.clear()
        _warned_minute = False
        _warned_day = False


def acquire_tray_quota(settings: Any | None = None) -> None:
    per_minute = int(getattr(settings, "tray_rate_limit_per_minute", 90) or 0)
    per_day = int(getattr(settings, "tray_rate_limit_per_day", 4000) or 0)
    if per_minute <= 0 and per_day <= 0:
        return

    now = time.time()
    global _warned_minute, _warned_day
    with _lock:
        while _minute_events and now - _minute_events[0] > 60:
            _minute_events.popleft()
        while _day_events and now - _day_events[0] > 86400:
            _day_events.popleft()

        minute_count = len(_minute_events)
        day_count = len(_day_events)
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

        _minute_events.append(now)
        _day_events.append(now)
        minute_count += 1
        day_count += 1

        if per_minute > 0 and minute_count >= int(per_minute * 0.8):
            if not _warned_minute:
                logger.warning(
                    "Tray per-minute quota at %s/%s on this instance",
                    minute_count,
                    per_minute,
                )
                _warned_minute = True
        else:
            _warned_minute = False

        if per_day > 0 and day_count >= int(per_day * 0.8):
            if not _warned_day:
                logger.warning(
                    "Tray per-day quota at %s/%s on this instance",
                    day_count,
                    per_day,
                )
                _warned_day = True
        else:
            _warned_day = False
