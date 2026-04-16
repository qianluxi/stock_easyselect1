"""
network.py

统一网络配置：
- 禁用系统代理
- 测试 Tushare 连接
- 简单重试机制
"""

import os
import time
import functools


# ==========================
# 禁用代理
# ==========================

def disable_proxy():

    proxy_keys = [
        "HTTP_PROXY", "HTTPS_PROXY",
        "http_proxy", "https_proxy",
        "ALL_PROXY", "all_proxy"
    ]

    for k in proxy_keys:
        os.environ[k] = ""

    os.environ["NO_PROXY"] = "*"

    print("[Network] Proxy disabled")


# ==========================
# Tushare连接测试
# ==========================

def test_tushare(pro):

    try:

        df = pro.trade_cal(
            exchange="SSE",
            start_date="20240101",
            end_date="20240110"
        )

        if df is None or df.empty:
            print("[Network] Tushare test failed")
            return False

        print("[Network] Tushare connection OK")
        return True

    except Exception as e:

        print("[Network] Tushare connection error:", e)
        return False


# ==========================
# 重试装饰器
# ==========================

def retry(max_retry=3, sleep=2):

    def decorator(func):

        @functools.wraps(func)
        def wrapper(*args, **kwargs):

            for i in range(max_retry):

                try:
                    return func(*args, **kwargs)

                except Exception as e:

                    print(f"[Retry] {func.__name__} error:", e)

                    if i < max_retry - 1:

                        print(f"[Retry] retry {i+1}/{max_retry}")
                        time.sleep(sleep)

            raise RuntimeError(f"{func.__name__} failed after retries")

        return wrapper

    return decorator