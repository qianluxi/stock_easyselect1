# 保存为 check_all_tables.py
from data.cache import DataCache
from stock_pool import STOCK_POOL
import pandas as pd

cache = DataCache("db/stock.db")
start = "2026-01-25"
end = "2026-06-14"

# 检查 daily_raw
df_raw = cache.load_raw_data(symbols=STOCK_POOL, start_date=start, end_date=end)
print("daily_raw 股票数:", df_raw['ts_code'].nunique(), "总记录:", len(df_raw))

# 检查 daily_basic
try:
    df_basic = cache.load_daily_basic(symbols=STOCK_POOL, start_date=start, end_date=end)
    print("daily_basic 股票数:", df_basic['ts_code'].nunique() if not df_basic.empty else 0, "总记录:", len(df_basic))
except Exception as e:
    print("daily_basic 加载失败:", e)

# 检查 adjust_factor
try:
    df_adj = cache.load_adjust_factor(symbols=STOCK_POOL, start_date=start, end_date=end)
    print("adjust_factor 股票数:", df_adj['ts_code'].nunique() if not df_adj.empty else 0, "总记录:", len(df_adj))
except Exception as e:
    print("adjust_factor 加载失败:", e)