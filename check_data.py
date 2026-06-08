# 保存为 check_db_stocks.py，放在项目根目录下运行
from data.cache import DataCache

cache = DataCache("db/stock.db")
df = cache.load_raw_data()  # 不加条件，获取所有数据
unique_stocks = df['ts_code'].unique()
print(f"数据库中的股票数量: {len(unique_stocks)}")
if len(unique_stocks) <= 30:
    print("股票列表:", sorted(unique_stocks))