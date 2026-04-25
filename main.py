"""
第二阶段使用示例 - 遍历所有预设策略
"""

from pathlib import Path
from screener import StockScreener
from strategies.configs import STRATEGY_LIBRARY


def main():
    db_path = Path(__file__).parent / "db" / "stock.db"
    screener = StockScreener(str(db_path))

    print("最新交易日:", screener.get_latest_trade_date())

    # 定义各策略推荐的展示列（若未定义则使用默认列）
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

    # 遍历策略库中的所有策略
    for i, (strategy_key, strategy_config) in enumerate(STRATEGY_LIBRARY.items(), 1):
        print("\n" + "=" * 60)
        print(f"策略{i}: {strategy_config['name']} ({strategy_config.get('type', 'unknown')})")
        if 'description' in strategy_config:
            print(f"描述: {strategy_config['description']}")
        print("=" * 60)

        try:
            result = screener.run_strategy(strategy_key, top_n=10)
        except Exception as e:
            print(f"执行失败: {e}")
            continue

        # 获取该策略的推荐展示列
        columns = display_columns_map.get(strategy_key)
        screener.print_result(result, columns=columns)

    # 可选：保留自定义策略示例
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
    }
    result_custom = screener.run_custom_strategy(custom_config)
    screener.print_result(result_custom, columns=["ts_code", "rsi_14", "pct_chg", "close"])


if __name__ == "__main__":
    main()