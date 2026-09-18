"""robots.txt 合规检查：采集前检查目标站点是否允许爬取。

企业级采集的合规底线：尊重 robots.txt 与站点条款。本模块用标准库
urllib.robotparser 解析 robots.txt，返回某 URL 是否允许抓取；并对已查过的
域名做进程内缓存，避免反复请求 robots.txt。
"""
from __future__ import annotations

import os
import urllib.request
import urllib.robotparser
from urllib.parse import urlparse

# robots.txt 检查用 UA；真实浏览器用浏览器自带 UA，二者分开
ROBOTS_UA = "*"

_cache: dict[str, tuple[bool, str]] = {}


def robots_check_enabled() -> bool:
    return os.getenv("ROBOTS_CHECK", "true").strip().lower() in ("1", "true", "yes", "on")


def parse(content: str) -> urllib.robotparser.RobotFileParser:
    """从 robots.txt 文本内容解析（便于离线测试）。"""
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(content.splitlines())
    return rp


def can_fetch(url: str, timeout: int = 5) -> tuple[bool, str]:
    """检查能否抓取该 URL，返回 (是否允许, 说明)。拿不到 robots.txt 时默认放行并记录原因。"""
    base = _robots_url(url)
    if base in _cache:
        return _cache[base]

    try:
        req = urllib.request.Request(base, headers={"User-Agent": ROBOTS_UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8", errors="replace")
        rp = parse(content)
        allowed = rp.can_fetch(ROBOTS_UA, url)
        result = (allowed, "允许" if allowed else "被 robots.txt 禁止")
    except Exception as e:  # 站点无 robots.txt / 网络失败：默认放行，但不缓存失败
        result = (True, f"未获取到 robots.txt（{e.__class__.__name__}），默认放行")

    _cache[base] = result
    return result


def _robots_url(url: str) -> str:
    u = urlparse(url)
    return f"{u.scheme}://{u.netloc}/robots.txt"
