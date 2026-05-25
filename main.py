"""
第二阶段使用示例 - 遍历所有策略 + 共振分析 + 导出 Excel
"""

from pathlib import Path
import pandas as pd
from screener import StockScreener
from strategies.configs import STRATEGY_LIBRARY

#以下为调试语句
from data.cache import DataCache
from stock_pool import STOCK_POOL

cache = DataCache("db/stock.db")
# 直接查询 daily_basic 表任意 5 行
import sqlite3
conn = sqlite3.connect("db/stock.db")
df_check = pd.read_sql("SELECT * FROM daily_basic LIMIT 5", conn)
conn.close()
print("daily_basic 表前5行：")
print(df_check)
print("\n日期示例:", df_check['trade_date'].iloc[0] if not df_check.empty else '无')

# 再测试我们的加载函数
df_basic = cache.load_daily_basic(STOCK_POOL[:5], '20230101', '20250429')
print("\n通过 load_daily_basic 加载的形状:", df_basic.shape)
if not df_basic.empty:
    print(df_basic.head())
#以上为调试语句

def main():
    db_path = Path(__file__).parent / "db" / "stock.db"
    screener = StockScreener(str(db_path))
    latest_date = screener.get_latest_trade_date()
    print("最新交易日:", latest_date)

    # ========== 涨停过滤开关 ==========
    # 可选值："all"（保守，过滤所有涨停）、"strict"（稳健，只过滤一字板/T字板）、None（不过滤）
    LIMIT_UP_FILTER = "all"       # 用户在此修改
    # ==================================

    # 定义各策略展示列
    display_columns_map = {
        "healthy_volume_rise": ["ts_code", "pct_chg", "volume_ratio", "turnover", "close", "circ_mv", "pe_ttm"],
        "momentum_breakout": ["ts_code", "ret_5", "vol_ratio_5", "pct_chg", "close"],
        "ma_golden_cross": ["ts_code", "ma_5", "ma_20", "pct_chg", "volume_ratio"],
        "low_vol_high_turnover": ["ts_code", "volatility_20", "turnover", "pct_chg"],
        "atr_breakout": ["ts_code", "atr_14", "pct_chg", "close"],
        "rsi_oversold_rebound": ["ts_code", "rsi_14", "pct_chg", "close"],
        "macd_bullish": ["ts_code", "dif", "dea", "macd", "pct_chg"],
        "value_momentum": ["ts_code", "ret_20", "pe_ttm", "pct_chg", "close"],
    }

    # 用于收集每个策略的结果（用于共振分析和导出）
    all_results = {}
    # 用于共振统计：{ts_code: {"count": n, "strategies": [name1, name2]}}
    resonance = {}

    # 遍历策略库中的所有策略
    for strategy_key, strategy_config in STRATEGY_LIBRARY.items():
        strategy_name = strategy_config["name"]
        print("\n" + "=" * 60)
        print(f"策略: {strategy_name} ({strategy_config.get('type', 'unknown')})")
        if "description" in strategy_config:
            print(f"描述: {strategy_config['description']}")
        print("=" * 60)

        try:
            result = screener.run_strategy(strategy_key, top_n=50,
                                           exclude_limit_up=LIMIT_UP_FILTER)  # 传递开关
        except Exception as e:
            print(f"执行失败: {e}")
            result = pd.DataFrame()

        all_results[strategy_name] = result

        # 打印结果
        columns = display_columns_map.get(strategy_key)
        if not result.empty:
            screener.print_result(result, columns=columns)
        else:
            print("未找到符合条件的股票。")

        # 收集共振数据
        if not result.empty:
            for code in result["ts_code"]:
                if code not in resonance:
                    resonance[code] = {"count": 0, "strategies": []}
                resonance[code]["count"] += 1
                resonance[code]["strategies"].append(strategy_name)

    # ---------- 自定义策略 ----------
    print("\n" + "=" * 60)
    print("自定义策略: RSI < 30 且 当日涨幅 > 2%")
    print("=" * 60)
    custom_config = {
        "name": "自定义RSI超卖",
        "type": "window",
        "window": 30,
        "factors": ["rsi_14"],
        "filters": [
            ("rsi_14", "<", 30),
            ("pct_chg", ">", 2.0),
        ],
        "sort_by": "rsi_14",
        "ascending": True,
        "top_n": 10,
        "keep_last_only": True,
        "exclude_limit_up": LIMIT_UP_FILTER,   # 添加这一行
    }
    custom_result = screener.run_custom_strategy(custom_config)
    all_results["自定义RSI超卖"] = custom_result
    if not custom_result.empty:
        screener.print_result(custom_result, columns=["ts_code", "rsi_14", "pct_chg", "close"])
        for code in custom_result["ts_code"]:
            if code not in resonance:
                resonance[code] = {"count": 0, "strategies": []}
            resonance[code]["count"] += 1
            resonance[code]["strategies"].append("自定义RSI超卖")
    else:
        print("未找到符合条件的股票。")

    # ---------- 共振分析 ----------
    print("\n" + "=" * 60)
    print("策略共振分析（高共识标的）")
    print("=" * 60)
    if resonance:
        resonance_df = pd.DataFrame([
            {
                "ts_code": code,
                "共振次数": info["count"],
                "涉及策略": "，".join(info["strategies"])
            }
            for code, info in resonance.items()
        ])
        resonance_df = resonance_df.sort_values("共振次数", ascending=False).reset_index(drop=True)
        print(resonance_df.to_string(index=False))
    else:
        resonance_df = pd.DataFrame()
        print("无股票同时被多个策略选中。")

    # ---------- 导出 Excel ----------
    excel_path = Path(__file__).parent / f"选股结果_{latest_date}.xlsx"
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        # 导出各策略结果
        for sheet_name, df in all_results.items():
            # Excel sheet 名称最长 31 字符
            safe_name = sheet_name[:31]
            df.to_excel(writer, sheet_name=safe_name, index=False)
        # 导出共振分析
        if not resonance_df.empty:
            resonance_df.to_excel(writer, sheet_name="共振分析", index=False)
    print(f"\n结果已导出至: {excel_path}")


if __name__ == "__main__":
    main()