"""
盘中实时筛选（混合数据源方案） + 共振分析 + 导出 Excel
每天 14:30 后运行，利用历史数据库 + efinance 实时行情
"""

from pathlib import Path
import pandas as pd
from screener import StockScreener
from core.efinance_live_loader import EfinanceLiveLoader
from strategies.configs import STRATEGY_LIBRARY


def main():
    db_path = Path(__file__).parent / "db" / "stock.db"
    live_loader = EfinanceLiveLoader(str(db_path))

    screener = StockScreener(str(db_path))
    screener.set_live_loader(live_loader)

    # 全局默认涨停过滤，策略配置中的设置会覆盖它
    DEFAULT_LIMIT_UP_FILTER = "all"

    # 用于收集各策略结果和共振统计
    all_results = {}
    resonance = {}       # {ts_code: {"count": n, "strategies": [name1, name2]}}

    # 定义各策略推荐展示列（与盘后一致）
    display_columns_map = {
        "healthy_volume_rise": ["ts_code", "pct_chg", "volume_ratio", "turnover", "close", "circ_mv", "pe_ttm"],
        "momentum_breakout": ["ts_code", "ret_5", "vol_ratio_5", "pct_chg", "close"],
        "ma_golden_cross": ["ts_code", "ma_5", "ma_20", "pct_chg", "volume_ratio"],
        "low_vol_high_turnover": ["ts_code", "volatility_20", "turnover", "pct_chg"],
        "atr_breakout": ["ts_code", "atr_14", "pct_chg", "close"],
        "rsi_oversold_rebound": ["ts_code", "rsi_14", "pct_chg", "close"],
        "macd_bullish": ["ts_code", "dif", "dea", "macd", "pct_chg"],
        "value_momentum": ["ts_code", "ret_20", "pe_ttm", "pct_chg", "close"],
        "live_non_limit_up_healthy": ["ts_code", "pct_chg", "volume_ratio", "turnover", "close", "pe_ttm"],
        "live_safe_healthy": ["ts_code", "pct_chg", "volume_ratio", "turnover", "close", "pe_ttm"],
    }

    # 遍历所有策略
    for key, cfg in STRATEGY_LIBRARY.items():
        name = cfg["name"]
        print("\n" + "=" * 60)
        print(f"【实时】策略: {name}")
        if "description" in cfg:
            print(f"描述: {cfg['description']}")
        print("=" * 60)

        # 涨停过滤：策略自身优先，否则用全局默认
        filter_mode = cfg.get("exclude_limit_up", DEFAULT_LIMIT_UP_FILTER)

        try:
            result = screener.run_strategy(
                key,
                top_n=20,
                exclude_limit_up=filter_mode,
            )
        except Exception as e:
            print(f"执行失败: {e}")
            result = pd.DataFrame()

        all_results[name] = result

        # 打印结果
        columns = display_columns_map.get(key)
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
                resonance[code]["strategies"].append(name)

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
    # 使用当天日期作为文件名
    from datetime import datetime
    today_str = datetime.today().strftime("%Y-%m-%d")
    excel_path = Path(__file__).parent / f"选股结果_实时_{today_str}.xlsx"
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        # 导出各策略结果
        for sheet_name, df in all_results.items():
            safe_name = sheet_name[:31]  # Excel sheet 名称最长 31 字符
            df.to_excel(writer, sheet_name=safe_name, index=False)
        # 导出共振分析
        if not resonance_df.empty:
            resonance_df.to_excel(writer, sheet_name="共振分析", index=False)
    print(f"\n结果已导出至: {excel_path}")


if __name__ == "__main__":
    main()