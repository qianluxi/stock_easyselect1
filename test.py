import efinance as ef

# 获取全市场实时行情
df = ef.stock.get_realtime_quotes()

# 检查量比字段
print("列名:", df.columns.tolist())
if '量比' in df.columns:
    print("\n量比字段样例：")
    print(df['量比'].head(10))
    print("\n量比有效值数量：", df['量比'].notna().sum())
else:
    print("\n❌ 没有'量比'字段！")