"""
ETF 股票池生成（行业均衡 + 流动性筛选）

策略：
1. 获取全部ETF
2. 获取最近20个交易日全市场ETF成交额
3. 计算20日均成交额
4. 按行业分类
5. 每个行业按流动性排序取Top N
6. 输出均衡ETF池
"""

import sys
import time
import pandas as pd
import tushare as ts

from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import TS_TOKEN
from utils.network import disable_proxy

disable_proxy()

ts.set_token(TS_TOKEN)
pro = ts.pro_api()

# =========================
# 参数配置
# =========================

LOOKBACK_DAYS = 20

# 千元单位
MIN_AMOUNT_THRESHOLD = 50000  # 5000万元过滤线

# 每类ETF配额（核心）
CATEGORY_LIMITS = {
    "宽基": 15,
    "红利": 5,
    "金融": 5,
    "消费": 5,
    "医药": 5,
    "科技": 8,
    "新能源": 5,
    "军工": 3,
    "周期": 5,
    "港股": 5,
    "海外": 10,   # 按你的要求：海外10只
    "商品": 3,
    "人工智能":3,
    "债券": 3,
}

# =========================
# ETF分类规则（基于名称关键词）
# =========================

def classify_etf(name: str) -> str:
    if any(k in name for k in ["上证50", "沪深300", "中证500", "中证1000", "创业板", "科创"]):
        return "宽基"

    if "红利" in name:
        return "红利"

    if any(k in name for k in ["银行", "证券", "金融"]):
        return "金融"

    if any(k in name for k in ["消费", "白酒", "食品", "家电"]):
        return "消费"

    if any(k in name for k in ["医药", "医疗", "生物"]):
        return "医药"
    
    if any(k in name for k in ["人工智能", "AI", "机器人", "智能驾驶", "智能汽车", "智能制造", "大数据", "云计算"]):
        return "人工智能"

    if any(k in name for k in ["半导体", "芯片", "5G", "软件", "云计算", "通信"]):
        return "科技"

    if any(k in name for k in ["新能源", "光伏", "电池", "锂"]):
        return "新能源"

    if "军工" in name:
        return "军工"

    if any(k in name for k in ["有色", "煤炭", "钢铁", "化工"]):
        return "周期"

    if any(k in name for k in ["恒生", "港股", "中概"]):
        return "港股"

    if any(k in name for k in ["纳斯达克", "标普", "德国", "日经", "海外"]):
        return "海外"

    if any(k in name for k in ["黄金", "商品", "原油", "稀土"]):
        return "商品"

    if any(k in name for k in ["国债", "债券", "可转债"]):
        return "债券"

    return "其他"


# =========================
# ETF列表
# =========================

def get_etf_list():
    print("获取ETF基础数据...")

    df = pro.fund_basic(
        market='E',
        fields='ts_code,name'
    )

    if df.empty:
        return df

    df = df[
        ~df["name"].str.contains("联接", na=False)
    ]

    df["category"] = df["name"].apply(classify_etf)

    print(f"ETF总数: {len(df)}")

    return df


# =========================
# 交易日
# =========================

def get_recent_trade_dates(n=20):

    end_date = datetime.now().strftime("%Y%m%d")

    start_date = (
        datetime.now() - timedelta(days=80)
    ).strftime("%Y%m%d")

    cal = pro.trade_cal(
        start_date=start_date,
        end_date=end_date,
        is_open='1'
    )

    dates = cal["cal_date"].sort_values().tolist()

    return dates[-n:]


# =========================
# 拉取行情
# =========================

def get_fund_daily(trade_dates):

    dfs = []

    for i, d in enumerate(trade_dates, 1):

        try:

            df = pro.fund_daily(
                trade_date=d,
                fields="ts_code,trade_date,amount"
            )

            if not df.empty:
                dfs.append(df)

            print(f"[{i}/{len(trade_dates)}] {d} -> {len(df)}")

            time.sleep(0.3)

        except Exception as e:
            print("error:", e)

    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()


# =========================
# 计算流动性
# =========================

def calc_liquidity(etf_df, daily_df):

    daily_df["amount"] = pd.to_numeric(
        daily_df["amount"],
        errors="coerce"
    )

    daily_df = daily_df.dropna(subset=["amount"])

    avg = (
        daily_df.groupby("ts_code")["amount"]
        .mean()
        .reset_index()
        .rename(columns={"amount": "avg_amount"})
    )

    df = etf_df.merge(avg, on="ts_code", how="inner")

    df = df[df["avg_amount"] >= MIN_AMOUNT_THRESHOLD]

    return df


# =========================
# 行业均衡筛选
# =========================

def build_balanced_pool(df):

    result = []

    for cat, limit in CATEGORY_LIMITS.items():

        sub = df[df["category"] == cat]

        sub = sub.sort_values(
            "avg_amount",
            ascending=False
        )

        picked = sub.head(limit)

        result.append(picked)

        print(f"{cat}: {len(picked)}")

    if result:
        return pd.concat(result)

    return pd.DataFrame()


# =========================
# 输出
# =========================

def save_pool(df):

    df = df.sort_values(
        "avg_amount",
        ascending=False
    )

    pool_file = (
        Path(__file__).parent.parent
        / "etf_pool.py"
    )

    lines = [
        '"""',
        'ETF 股票池（行业均衡 + 流动性筛选）',
        f'生成时间: {datetime.now()}',
        f'近{LOOKBACK_DAYS}日均成交额 >= {MIN_AMOUNT_THRESHOLD}',
        '"""',
        '',
        'ETF_POOL = ['
    ]

    for _, r in df.iterrows():
        lines.append(
            f'    "{r["ts_code"]}",  # {r["name"]}'
        )

    lines.append(']')

    pool_file.write_text(
        "\n".join(lines),
        encoding="utf-8"
    )

    print("\n完成:")
    print("数量:", len(df))
    print("路径:", pool_file.resolve())


# =========================
# 主流程
# =========================

def main():

    etf = get_etf_list()

    dates = get_recent_trade_dates(LOOKBACK_DAYS)

    daily = get_fund_daily(dates)

    if daily.empty:
        print("无数据")
        return

    df = calc_liquidity(etf, daily)

    if df.empty:
        print("无流动性ETF")
        return

    balanced = build_balanced_pool(df)

    save_pool(balanced)


if __name__ == "__main__":
    main()