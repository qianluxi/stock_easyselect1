"""
生成全 A 股股票池（仅保留沪深正常上市股票，剔除 ST、退市等）
调用 Tushare stock_basic 接口，写入 stock_pool.py
"""

import sys
import time
from pathlib import Path
import pandas as pd
import tushare as ts

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import TS_TOKEN
from utils.network import disable_proxy

disable_proxy()
ts.set_token(TS_TOKEN)
pro = ts.pro_api()

# 过滤条件：只保留沪深两市，上市状态为“上市”或“正常”
EXCHANGES = ['SSE', 'SZSE']   # 上交所、深交所
STATUS = ['L', 'N']           # L=上市, N=正常(部分接口用)


def get_all_stocks():
    """获取全部 A 股基础信息，并过滤"""
    print("正在获取全市场股票列表...")
    try:
        df = pro.stock_basic(
            exchange='',
            list_status='L',
            fields='ts_code,symbol,name,area,industry,list_date,exchange'
        )
    except Exception as e:
        print(f"获取失败: {e}")
        return pd.DataFrame()

    if df.empty:
        print("未获取到股票数据")
        return df

    # 仅保留指定交易所
    df = df[df['exchange'].isin(EXCHANGES)]
    # 过滤掉名称含 "ST" 的股票（退市风险警示）
    df = df[~df['name'].str.contains('ST', na=False)]
    # 过滤掉退市整理的股票（通常代码为 400 开头，也可按 list_status 过滤）
    # Tushare list_status='L' 已经代表上市，这里只做双重保险
    df = df[df['ts_code'].str.startswith(('000', '001', '002', '003', '300', '301', '600', '601', '603', '605', '688'))]

    print(f"共获取 {len(df)} 只正常上市 A 股")
    return df


def save_pool(stock_df):
    """生成 stock_pool.py 文件"""
    pool_file = Path(__file__).parent.parent / "stock_pool.py"
    lines = [
        '"""',
        '股票池（全 A 股，自动生成）',
        f'生成时间: {pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")}',
        f'数量: {len(stock_df)}',
        '"""',
        '',
        'STOCK_POOL = ['
    ]
    for code in sorted(stock_df['ts_code']):
        lines.append(f'    "{code}",')
    lines.append(']')
    lines.append('')
    pool_file.write_text('\n'.join(lines), encoding='utf-8')
    print(f"已生成 {pool_file}，共 {len(stock_df)} 只股票。")


def main():
    df = get_all_stocks()
    if df.empty:
        print("无数据，退出。")
        return
    save_pool(df)


if __name__ == "__main__":
    main()