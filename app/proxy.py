"""IP 代理池：轮换代理，降低单 IP 高频访问被限流/封禁的风险。

代理来源（优先级）：PROXY_POOL（逗号分隔多代理）> PROXY（单代理）> PROXY_FILE（每行一个）。
browser-use 0.13 用 `ProxySettings(server, username, password)` 配置代理，本模块负责
解析「scheme://user:pass@host:port」并做轮换。未配置任何代理时 next() 返回 None（直连）。
"""
from __future__ import annotations

import os
import threading
from urllib.parse import urlparse

from browser_use.browser.profile import ProxySettings


def _load_proxies() -> list[str]:
    pool = os.getenv("PROXY_POOL", "")
    if pool:
        return [p.strip() for p in pool.split(",") if p.strip()]
    single = os.getenv("PROXY", "")
    if single:
        return [single.strip()]
    f = os.getenv("PROXY_FILE", "")
    if f and os.path.isfile(f):
        with open(f, encoding="utf-8") as fh:
            return [l.strip() for l in fh if l.strip() and not l.startswith("#")]
    return []


def _to_settings(url: str) -> ProxySettings:
    """把 'scheme://user:pass@host:port' 转成 ProxySettings（认证信息分离）。"""
    if "://" not in url:
        url = "http://" + url
    u = urlparse(url)
    host = u.hostname or ""
    port = f":{u.port}" if u.port else ""
    return ProxySettings(
        server=f"{u.scheme}://{host}{port}",
        username=u.username or None,
        password=u.password or None,
    )


class ProxyPool:
    """线程安全的代理池：round-robin 轮换。"""

    def __init__(self, proxies: list[str] | None = None):
        self._proxies = proxies if proxies is not None else _load_proxies()
        self._i = 0
        self._lock = threading.Lock()

    def __bool__(self) -> bool:
        return bool(self._proxies)

    def __len__(self) -> int:
        return len(self._proxies)

    def next(self) -> ProxySettings | None:
        """返回下一个代理的 ProxySettings；无代理返回 None。"""
        if not self._proxies:
            return None
        with self._lock:
            url = self._proxies[self._i % len(self._proxies)]
            self._i += 1
        return _to_settings(url)
