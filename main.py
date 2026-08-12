"""
第二阶段使用示例 - 遍历所有策略 + 共振分析 + 导出 Excel
新增：通过 RUN_MODE 开关控制策略范围（'all' / 'stock' / 'etf'）
新增：run_all_strategies() 供命令行与 Web 界面共用（选股逻辑不变）
"""

from pathlib import Path
from typing import Callable, Dict, Optional
import pandas as pd
from screener import StockScreener
from strategies.configs import STRATEGY_LIBRARY

# ========== 运行模式开关 ==========
# 可选值：'all'（全部）、'stock'（仅个股）、'etf'（仅ETF）
RUN_MODE = "stock"
# ==================================

# 定义各策略展示列
DISPLAY_COLUMNS_MAP = {
    "healthy_volume_rise": ["ts_code", "pct_chg", "volume_ratio", "turnover_rate", "close", "circ_mv", "pe_ttm"],
    "momentum_breakout": ["ts_code", "ret_5", "vol_ratio_5", "pct_chg", "close"],
    "ma_golden_cross": ["ts_code", "ma_5", "ma_20", "pct_chg", "volume_ratio"],
    "low_vol_high_turnover": ["ts_code", "volatility_20", "turnover_rate", "pct_chg"],
    "atr_breakout": ["ts_code", "atr_14", "pct_chg", "close"],
    "rsi_oversold_rebound": ["ts_code", "rsi_14", "pct_chg", "close"],
    "macd_bullish": ["ts_code", "dif", "dea", "macd", "pct_chg"],
    "value_momentum": ["ts_code", "ret_20", "pe_ttm", "pct_chg", "close"],
    "etf_momentum": ["ts_code", "ret_20", "pct_chg", "close"],    # 新增 ETF 策略展示列
}

# 自定义策略配置：RSI < 30 且 当日涨幅 > 2%（与命令行版一致）
CUSTOM_STRATEGY_CONFIG = {
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
    "exclude_limit_up": "all",
    # 默认 pool_type 为 'stock'，若想只对 ETF 运行可改为 'etf'
}


def strategy_belongs_to_mode(strategy_config, mode):
    """根据运行模式判断策略是否应该被执行"""
    if mode == "all":
        return True
    # 获取策略的 pool_type，默认为 'stock'
    pool_type = strategy_config.get("pool_type", "stock")
    if mode == "stock" and pool_type == "stock":
        return True
    if mode == "etf" and pool_type == "etf":
        return True
    return False


def run_all_strategies(
    mode: str = "stock",
    limit_up_filter: str = "all",
    top_n: int = 50,
    db_path: Optional[str] = None,
    excel_path: Optional[Path] = None,
    progress_callback: Optional[Callable[[str, pd.DataFrame], None]] = None,
) -> Dict[str, object]:
    """
    遍历所有策略 + 共振分析 + 导出 Excel（命令行与 Web 界面共用，逻辑不变）

    Parameters
    ----------
    mode : str
        'all' / 'stock' / 'etf'
    limit_up_filter : str
        涨停过滤开关，'all' 表示启用（命令行默认值），None/False 表示不启用
    top_n : int
        每个库内策略最多输出条数（命令行默认 50）
    db_path : str, optional
        数据库路径，默认使用工程内 db/stock.db
    excel_path : Path, optional
        导出路径，默认导出到工程目录 选股结果_{latest_date}.xlsx
    progress_callback : callable, optional
        每个策略跑完后回调 progress_callback(策略名, 结果DataFrame)

    Returns
    -------
    dict
        all_results（策略名 -> DataFrame）、resonance_df、latest_date、excel_path
    """
    db_path = Path(db_path) if db_path else Path(__file__).parent / "db" / "stock.db"
    screener = StockScreener(str(db_path))
    latest_date = screener.get_latest_trade_date()
    print("最新交易日:", latest_date)

    all_results = {}
    resonance = {}

    # 遍历策略库中的所有策略，根据 mode 过滤
    for strategy_key, strategy_config in STRATEGY_LIBRARY.items():
        # 关键：模式过滤
        if not strategy_belongs_to_mode(strategy_config, mode):
            continue

        strategy_name = strategy_config["name"]
        print("\n" + "=" * 60)
        print(f"策略: {strategy_name} ({strategy_config.get('type', 'unknown')})")
        if "description" in strategy_config:
            print(f"描述: {strategy_config['description']}")
        print("=" * 60)

        try:
            result = screener.run_strategy(strategy_key, top_n=top_n,
                                           exclude_limit_up=limit_up_filter)
        except Exception as e:
            print(f"执行失败: {e}")
            result = pd.DataFrame()

        all_results[strategy_name] = result

        columns = DISPLAY_COLUMNS_MAP.get(strategy_key)
        if not result.empty:
            screener.print_result(result, columns=columns)
        else:
            print("未找到符合条件的股票。")

        if not result.empty:
            for code in result["ts_code"]:
                if code not in resonance:
                    resonance[code] = {"count": 0, "strategies": []}
                resonance[code]["count"] += 1
                resonance[code]["strategies"].append(strategy_name)

        if progress_callback is not None:
            progress_callback(strategy_name, result)

    # ---------- 自定义策略：也可通过 pool_type 区分（默认 stock）----------
    print("\n" + "=" * 60)
    print("自定义策略: RSI < 30 且 当日涨幅 > 2%")
    print("=" * 60)
    custom_config = dict(CUSTOM_STRATEGY_CONFIG)
    custom_config["exclude_limit_up"] = limit_up_filter
    # 根据模式决定是否运行自定义策略
    if strategy_belongs_to_mode(custom_config, mode):
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
        if progress_callback is not None:
            progress_callback("自定义RSI超卖", custom_result)
    else:
        print("已跳过（当前运行模式不包含该策略）。")

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
    excel_path = excel_path if excel_path else Path(__file__).parent / f"选股结果_{latest_date}.xlsx"
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        for sheet_name, df in all_results.items():
            safe_name = sheet_name[:31]
            df.to_excel(writer, sheet_name=safe_name, index=False)
        if not resonance_df.empty:
            resonance_df.to_excel(writer, sheet_name="共振分析", index=False)
    print(f"\n结果已导出至: {excel_path}")

    return {
        "all_results": all_results,
        "resonance_df": resonance_df,
        "latest_date": latest_date,
        "excel_path": Path(excel_path),
    }


def main():
    """命令行入口：按 RUN_MODE 运行全部策略并导出 Excel（原逻辑不变）"""
    run_all_strategies(mode=RUN_MODE)


if __name__ == "__main__":
    main()
