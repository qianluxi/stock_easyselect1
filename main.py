"""
第二阶段使用示例
展示预设策略和自定义策略的调用方式
"""

from pathlib import Path
from screener import StockScreener


def main():
    db_path = Path(__file__).parent / "db" / "stock.db"
    screener = StockScreener(str(db_path))

    print("最新交易日:", screener.get_latest_trade_date())

    # ---------- 示例1：运行预设策略 ----------
    print("\n" + "=" * 60)
    print("策略1: 健康放量上涨 (单日)")
    print("=" * 60)
    result1 = screener.run_strategy("healthy_volume_rise", top_n=10)
    screener.print_result(result1)

    print("\n" + "=" * 60)
    print("策略2: 动量突破 (多日窗口)")
    print("=" * 60)
    result2 = screener.run_strategy("momentum_breakout", top_n=10)
    columns = ["ts_code", "ret_5", "vol_ratio_5", "pct_chg", "close"]
    screener.print_result(result2, columns=columns)

    print("\n" + "=" * 60)
    print("策略3: 均线金叉")
    print("=" * 60)
    result3 = screener.run_strategy("ma_golden_cross", top_n=10)
    columns = ["ts_code", "ma_5", "ma_20", "pct_chg", "volume_ratio"]
    screener.print_result(result3, columns=columns)

    print("\n" + "=" * 60)
    print("策略4: 低波高换手")
    print("=" * 60)
    result4 = screener.run_strategy("low_vol_high_turnover", top_n=10)
    columns = ["ts_code", "volatility_20", "turnover", "pct_chg"]
    screener.print_result(result4, columns=columns)

    # ---------- 示例2：自定义策略（临时） ----------
    print("\n" + "=" * 60)
    print("自定义策略: RSI < 30 且 5日涨幅 > 2%")
    print("=" * 60)
    custom_config = {
        "name": "自定义RSI超卖",
        "type": "window",
        "window": 30,
        "factors": ["rsi_14", "ret_5"],
        "filters": [
            ("rsi_14", "<", 30),
            ("ret_5", ">", 0.02),
        ],
        "sort_by": "rsi_14",
        "ascending": True,
        "top_n": 10,
        "keep_last_only": True,
    }
    result_custom = screener.run_custom_strategy(custom_config)
    columns = ["ts_code", "rsi_14", "ret_5", "pct_chg", "close"]
    screener.print_result(result_custom, columns=columns)


if __name__ == "__main__":
    main()