"""行为拟人化 + 域名限流：降低被行为风控 / 频控识别的概率。

- 拟人化：浏览器动作之间加随机延迟（接 browser-use 的 wait_between_actions），
  可选自定义 User-Agent，让请求节奏更接近真人。
- 域名限流：对同一域名两次采集之间保持最小间隔，避免高频触发封禁。
"""
from __future__ import annotations

import asyncio
import os
import random
import threading
import time
from urllib.parse import urlparse


def humanize_enabled() -> bool:
    return os.getenv("HUMANIZE", "true").strip().lower() in ("1", "true", "yes", "on")


def action_delay() -> float:
    """动作间随机延迟（秒）。HUMANIZE=false 时返回 0。"""
    if not humanize_enabled():
        return 0.0
    lo = float(os.getenv("HUMANIZE_DELAY_MIN", "0.5"))
    hi = float(os.getenv("HUMANIZE_DELAY_MAX", "2.0"))
    return round(random.uniform(lo, hi), 2)


def user_agent() -> str | None:
    """自定义 User-Agent（未配置返回 None，用浏览器默认）。"""
    return os.getenv("USER_AGENT") or None


class DomainRateLimiter:
    """同域名最小间隔限流（线程安全）。"""

    def __init__(self, min_interval: float | None = None):
        self.min_interval = (
            min_interval
            if min_interval is not None
            else float(os.getenv("RATE_LIMIT_INTERVAL", "2.0"))
        )
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    async def wait_if_needed(self, url: str) -> float:
        """若距上次抓该域名不足 min_interval，则 sleep 补足。返回实际等待秒数。"""
        domain = urlparse(url).netloc
        now = time.monotonic()
        with self._lock:
            last = self._last.get(domain, 0.0)
            wait = max(0.0, self.min_interval - (now - last))
            self._last[domain] = now + wait
        if wait > 0:
            await asyncio.sleep(wait)
        return round(wait, 2)
