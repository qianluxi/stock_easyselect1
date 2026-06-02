"""
单日策略回测示例（修复版）
"""

import pandas as pd
from pathlib import Path
from core.backtester import SingleDayBacktester
from strategies.configs import STRATEGY_LIBRARY


def main():
    db_path = Path(__file__).parent / "db" / "stock.db"

    # 选择要回测的策略（健康放量上涨）
    strategy = STRATEGY_LIBRARY["healthy_volume_rise"].copy()
    strategy["apply_quality_filter"] = False   # 回测时关闭额外过滤，保持简洁
    strategy["exclude_limit_up"] = None        # 不剔除涨停，观察原始表现

    backtester = SingleDayBacktester(str(db_path))

    result = backtester.run(
        strategy_config=strategy,
        start_date="2024-01-01",
        end_date="2026-04-27",
        hold_days=5,
        top_n=10
    )

    # 打印统计
    print("=" * 60)
    print(f"策略: {result.strategy_name}")
    print(f"回测区间: {result.start_date} → {result.end_date}")
    print(f"持有天数: {result.hold_days} 个交易日")
    print(f"每日最多买入: {result.top_n} 只")
    print("-" * 60)
    print(f"总交易次数: {result.total_trades}")
    print(f"胜率:        {result.win_rate:.2%}")
    print(f"平均收益率:  {result.mean_return:.4%}")
    print(f"中位数收益:  {result.median_return:.4%}")
    print(f"最大单笔收益: {result.max_return:.2%}")
    print(f"最大单笔亏损: {result.min_return:.2%}")
    print(f"盈亏比:      {result.profit_loss_ratio:.2f}")
    print(f"最大回撤:    {result.max_drawdown:.2%}")
    print(f"夏普比率:    {result.sharpe_ratio:.2f}")
    print("=" * 60)

    if not result.equity_curve.empty:
        final_capital = result.equity_curve["capital"].iloc[-1]
        print(f"最终净值: {final_capital:.4f} (起始1.00)")
        print("净值曲线前5行：")
        print(result.equity_curve.head())

    # 导出结果
    output_path = Path(__file__).parent / "回测结果.xlsx"
    with pd.ExcelWriter(output_path) as writer:
        result.trade_log.to_excel(writer, sheet_name="交易明细", index=False)
        result.equity_curve.to_excel(writer, sheet_name="净值曲线", index=False)
    print(f"结果已保存至 {output_path}")


if __name__ == "__main__":
    main()