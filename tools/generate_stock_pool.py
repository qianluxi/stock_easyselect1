# tools/generate_stock_pool.py

import sqlite3
import os
import re
import pandas as pd

# 数据库路径
DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "db",
    "stock.db"
)

# 输出目录（项目根目录）
OUTPUT_DIR = os.path.dirname(os.path.dirname(__file__))

def load_data():
    """从数据库加载股票基础信息和市值数据"""
    print("连接数据库:", DB_PATH)
    conn = sqlite3.connect(DB_PATH)

    # 股票基础信息
    df_basic = pd.read_sql("SELECT * FROM stock_basic", conn)
    # 市值信息（取最新交易日，这里简化为全量，实际应取最新日期）
    df_mv = pd.read_sql("SELECT * FROM daily_basic", conn)

    conn.close()

    print("stock_basic 行数:", len(df_basic))
    print("daily_basic 行数:", len(df_mv))

    # 合并
    df = pd.merge(df_basic, df_mv, on="ts_code", how="inner")

    # total_mv 单位：万元 → 转换为亿元
    df["total_mv"] = df["total_mv"] / 10000

    print("合并后行数:", len(df))
    return df

def choose_industry(df):
    """让用户选择行业"""
    industries = sorted(df["industry"].dropna().unique())
    print("\n可选行业：")
    for i, ind in enumerate(industries):
        print(f"{i}. {ind}")

    idx = int(input("\n请选择行业编号: "))
    selected = industries[idx]
    print("选择行业:", selected)
    return selected

def choose_market_cap():
    """让用户输入市值范围"""
    min_cap = float(input("请输入最小市值(亿): "))
    max_cap = float(input("请输入最大市值(亿): "))
    return min_cap, max_cap

def filter_stocks(df, industry, min_cap, max_cap):
    """根据行业和市值筛选股票，返回列表"""
    df_filtered = df[
        (df["industry"] == industry) &
        (df["total_mv"] >= min_cap) &
        (df["total_mv"] <= max_cap)
    ]

    print("筛选后股票数:", len(df_filtered))
    if len(df_filtered) == 0:
        print("⚠ 没有符合条件的股票")
        return []

    # 按市值降序
    df_filtered = df_filtered.sort_values("total_mv", ascending=False)

    # 取前300（可配置）
    df_filtered = df_filtered.head(300)

    return df_filtered["ts_code"].tolist()

def get_next_pool_number():
    """获取下一个可用的 stock_poolN.py 编号"""
    pattern = re.compile(r'^stock_pool(\d+)\.py$')
    max_num = 0
    for f in os.listdir(OUTPUT_DIR):
        match = pattern.match(f)
        if match:
            num = int(match.group(1))
            if num > max_num:
                max_num = num
    return max_num + 1

def save_individual_pool(stock_list, pool_number):
    """保存单个行业池文件，如 stock_pool1.py"""
    filename = f"stock_pool{pool_number}.py"
    filepath = os.path.join(OUTPUT_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"# 自动生成股票池 (行业池 {pool_number})\n")
        f.write("STOCK_POOL = [\n")
        for code in stock_list:
            f.write(f"    '{code}',\n")
        f.write("]\n")
    print(f"✅ {filename} 已生成，股票数量: {len(stock_list)}")
    return filepath

def merge_all_pools():
    """读取所有 stock_pool*.py 文件（除 stock_pool.py 外），合并去重，写入 stock_pool.py"""
    all_stocks = set()

    # 遍历目录下所有 stock_pool*.py 文件，但排除 stock_pool.py（如果有）
    for f in os.listdir(OUTPUT_DIR):
        if f.startswith("stock_pool") and f.endswith(".py") and f != "stock_pool.py":
            filepath = os.path.join(OUTPUT_DIR, f)
            # 执行该文件以获取 STOCK_POOL 变量（注意安全，仅限本目录）
            ns = {}
            with open(filepath, "r", encoding="utf-8") as code:
                exec(code.read(), ns)
            if "STOCK_POOL" in ns:
                all_stocks.update(ns["STOCK_POOL"])

    # 写入总的 stock_pool.py
    total_file = os.path.join(OUTPUT_DIR, "stock_pool.py")
    with open(total_file, "w", encoding="utf-8") as f:
        f.write("# 自动生成总股票池（合并所有行业池）\n")
        f.write("STOCK_POOL = [\n")
        for code in sorted(all_stocks):
            f.write(f"    '{code}',\n")
        f.write("]\n")
    print(f"✅ 总股票池 stock_pool.py 已更新，股票数量: {len(all_stocks)}")

def main():
    # 1. 加载数据
    df = load_data()

    # 2. 交互选择行业和市值
    industry = choose_industry(df)
    min_cap, max_cap = choose_market_cap()

    # 3. 筛选股票
    stock_list = filter_stocks(df, industry, min_cap, max_cap)
    if not stock_list:
        return

    # 4. 生成新的行业池文件
    next_num = get_next_pool_number()
    save_individual_pool(stock_list, next_num)

    # 5. 合并所有行业池，生成总池 stock_pool.py
    merge_all_pools()

if __name__ == "__main__":
    main()