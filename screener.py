"""
股票筛选器（第二阶段）
作为策略执行器的入口，提供简洁的接口
"""

from pathlib import Path
from typing import Optional, List, Dict, Any
import pandas as pd

from strategies.runner import StrategyRunner
from strategies.configs import STRATEGY_LIBRARY


class StockScreener:
    """股票筛选器"""

    def __init__(self, db_path: str):
        self.runner = StrategyRunner(db_path)

    def run_strategy(self, strategy_name: str, **overrides) -> pd.DataFrame:
        """
        按策略名称执行预设策略

        Parameters
        ----------
        strategy_name : str
            策略名称，需在 STRATEGY_LIBRARY 中存在
        **overrides :
            可覆盖策略配置中的参数，如 top_n=30, end_date='2026-04-16'

        Returns
        -------
        pd.DataFrame
            筛选结果
        """
        if strategy_name not in STRATEGY_LIBRARY:
            raise ValueError(f"未知策略: {strategy_name}，可用策略: {list(STRATEGY_LIBRARY.keys())}")

        config = STRATEGY_LIBRARY[strategy_name].copy()
        config.update(overrides)
        return self.runner.run(config)

    def run_custom_strategy(self, config: Dict[str, Any]) -> pd.DataFrame:
        """执行自定义策略配置"""
        return self.runner.run(config)

    def get_latest_trade_date(self) -> Optional[str]:
        """获取最新交易日"""
        return self.runner.loader.get_latest_trade_date()

    def print_result(self, df: pd.DataFrame, columns: Optional[List[str]] = None) -> None:
        """格式化打印结果"""
        if df.empty:
            print("未找到符合条件的股票。")
            return
        if columns is None:
            columns = [
                "ts_code", "pct_chg", "volume_ratio", "turnover",
                "close", "circ_mv", "pe_ttm"
            ]
        available = [col for col in columns if col in df.columns]
        print(df[available].to_string(index=False))

    def set_live_loader(self, live_loader):
        """切换到实时数据加载器"""
        self.runner.loader = live_loader
        print("已切换至 efinance 实时行情模式")