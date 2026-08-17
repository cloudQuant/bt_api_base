"""统一限速器工厂（B-15：6 处限速器工厂收敛为一份实现）。"""

from __future__ import annotations

from bt_api_base.rate_limiter import RateLimiter, RateLimitRule, RateLimitScope, RateLimitType


def create_default_rate_limiter(
    exchange: str = "",
    *,
    global_limit: int = 1200,
    interval: int = 60,
) -> RateLimiter:
    """创建一个默认的滑动窗口限速器（1200 req/min，全局作用域）。"""
    return RateLimiter(
        rules=[
            RateLimitRule(
                name=f"{exchange}_default" if exchange else "default",
                limit=global_limit,
                interval=interval,
                type=RateLimitType.SLIDING_WINDOW,
                scope=RateLimitScope.GLOBAL,
            )
        ]
    )
