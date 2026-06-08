from data.cache import DataCache
import pandas as pd

cache = DataCache("db/stock.db")
df = cache.load_raw_data()
counts = df.groupby('ts_code').size()
low_count = counts[counts < 80]
print(f"记录少于80条的股票数量: {len(low_count)}")
print("示例代码:", low_count.index[:20].tolist())