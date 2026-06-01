"""
core/backtester.py
单日策略回测引擎
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import timedelta

from core.data_loader import DataLoader
from core.filter_engine import FilterEngine


@dataclass
class BacktestResult:
    """回测结果容器"""
    strategy_name: str
    start_date: str
    end_date: str
    hold_days: int
    top_n: int
    
    # 统计指标
    total_trades: int = 0
    win_rate: float = 0.0
    mean_return: float = 0.0
    median_return: float = 0.0
    max_return: float = 0.0
    min_return: float = 0.0
    profit_loss_ratio: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0          # 简易版，基于日收益
    
    # 每笔交易明细
    trade_log: pd.DataFrame = field(default_factory=pd.DataFrame)
    # 策略净值曲线
    equity_curve: pd.DataFrame = field(default_factory=pd.DataFrame)


class SingleDayBacktester:
    """单日策略回测器"""

    def __init__(self, db_path: str):
        self.loader = DataLoader(db_path)
        self.filter_engine = FilterEngine()

    def run(
        self,
        strategy_config: Dict[str, Any],
        start_date: str,
        end_date: str,
        hold_days: int = 5,
        top_n: int = 10,
        ts_codes: Optional[List[str]] = None,
    ) -> BacktestResult:
        """
        运行单日策略回测

        Parameters
        ----------
        strategy_config : dict
            策略配置（包含 filters, sort_by 等）
        start_date : str
            回测开始日期 YYYY-MM-DD
        end_date : str
            回测结束日期 YYYY-MM-DD
        hold_days : int
            买入后持有多少个交易日
        top_n : int
            每日最多买入股票数量
        ts_codes : list, optional
            限制股票池，默认使用全部

        Returns
        -------
        BacktestResult
        """
        # 获取交易日期列表（从数据库已有交易日）
        trade_days = self._get_trade_days(start_date, end_date)
        if len(trade_days) < hold_days + 1:
            raise ValueError("回测区间交易日不足，请扩大日期范围")

        # 预先加载整个回测区间的股票数据（提前缓存在内存中）
        price_data = self._load_price_data(start_date, end_date, ts_codes)
        
        # 准备交易日志和净值记录
        trade_records = []
        daily_returns = []
        capital = 1.0

        # 遍历每一个交易日（最后 hold_days 天不买入，避免未来数据）
        buy_dates = trade_days[:-hold_days]
        for i, buy_date in enumerate(buy_dates):
            # 1. 运行策略得到当日选股
            candidates = self._run_strategy_on_date(strategy_config, buy_date, price_data)
            if candidates.empty:
                continue

            # 取 top_n 只（已经按策略排序过）
            selected = candidates.head(top_n)

            # 2. 确定卖出日期（buy_date + hold_days 后的第一个交易日）
            sell_date = self._get_sell_date(trade_days, buy_date, hold_days)
            if sell_date is None:
                continue
            # 获取所有选中股票在卖出日的收盘价
            sell_prices = self._get_prices_on_date(price_data, sell_date, selected.index.tolist())
            buy_prices = selected["close"]

            # 3. 计算每只股票的收益率
            returns = sell_prices / buy_prices - 1
            valid_returns = returns.dropna()
            if valid_returns.empty:
                continue

            # 假设等权重分配，组合日收益率 = 平均个股收益率
            portfolio_return = valid_returns.mean()

            # 更新净值
            capital *= (1 + portfolio_return)
            daily_returns.append({
                "buy_date": buy_date,
                "sell_date": sell_date,
                "portfolio_return": portfolio_return,
                "capital": capital
            })

            # 记录每笔交易
            for ts_code in valid_returns.index:
                trade_records.append({
                    "buy_date": buy_date,
                    "ts_code": ts_code,
                    "ret": valid_returns[ts_code],
                    "sell_date": sell_date
                })

        # 如果没有成交，返回空结果
        if not trade_records:
            return BacktestResult(strategy_name=strategy_config.get("name", "unnamed"),
                                  start_date=start_date, end_date=end_date,
                                  hold_days=hold_days, top_n=top_n)

        trade_log = pd.DataFrame(trade_records)
        equity_curve = pd.DataFrame(daily_returns)

        # 计算统计指标
        stats = self._calculate_stats(trade_log, equity_curve)

        return BacktestResult(
            strategy_name=strategy_config.get("name", "unnamed"),
            start_date=start_date,
            end_date=end_date,
            hold_days=hold_days,
            top_n=top_n,
            total_trades=stats["total_trades"],
            win_rate=stats["win_rate"],
            mean_return=stats["mean_return"],
            median_return=stats["median_return"],
            max_return=stats["max_return"],
            min_return=stats["min_return"],
            profit_loss_ratio=stats["profit_loss_ratio"],
            max_drawdown=stats["max_drawdown"],
            sharpe_ratio=stats["sharpe_ratio"],
            trade_log=trade_log,
            equity_curve=equity_curve
        )

    def _get_trade_days(self, start_date: str, end_date: str) -> List[str]:
        """从数据库中获取区间内的所有交易日，按日期升序"""
        query = """
            SELECT DISTINCT trade_date 
            FROM daily_raw 
            WHERE trade_date BETWEEN ? AND ? 
            ORDER BY trade_date
        """
        import sqlite3
        conn = self.loader._get_connection()
        df = pd.read_sql_query(query, conn, params=(start_date, end_date))
        conn.close()
        return df["trade_date"].tolist()

    def _load_price_data(self, start_date: str, end_date: str, ts_codes: Optional[List[str]]) -> pd.DataFrame:
        """
        加载区间内所有股票的日线数据，以 (trade_date, ts_code) 为索引，方便快速查询
        """
        df = self.loader.load_window(start_date, end_date, ts_codes, include_basic=True)
        df = df.set_index(["trade_date", "ts_code"]).sort_index()
        return df

    def _run_strategy_on_date(self, config, trade_date, price_data):
        """在给定日期运行单日策略，返回包含排序列的DataFrame"""
        try:
            # 从预加载的 DataFrame 中提取当日截面数据
            # price_data 索引为 (trade_date, ts_code)，使用 xs 获取当日数据
            daily_slice = price_data.xs(trade_date, level="trade_date").copy()
        except KeyError:
            return pd.DataFrame()

        if daily_slice.empty:
            return daily_slice

        # 应用过滤条件
        filters = config.get("filters", [])
        filtered = self.filter_engine.apply_conditions(daily_slice, filters)
        if filtered.empty:
            return filtered

        # 排序
        sort_by = config.get("sort_by")
        ascending = config.get("ascending", False)
        if sort_by and sort_by in filtered.columns:
            filtered = filtered.sort_values(sort_by, ascending=ascending)

        return filtered

    def _get_sell_date(self, trade_days: List[str], buy_date: str, hold_days: int) -> Optional[str]:
        """找到买入日期后的 hold_days 个交易日对应的日期"""
        try:
            idx = trade_days.index(buy_date)
            sell_idx = idx + hold_days
            if sell_idx < len(trade_days):
                return trade_days[sell_idx]
        except ValueError:
            pass
        return None

    def _get_prices_on_date(self, price_data, date, ts_codes):
        """获取指定日期多个股票的收盘价"""
        try:
            slice_df = price_data.xs(date, level="trade_date")
            prices = slice_df["close"].reindex(ts_codes)
            return prices
        except KeyError:
            return pd.Series(index=ts_codes, dtype=float)

    def _calculate_stats(self, trade_log, equity_curve):
        """计算策略统计指标"""
        returns = trade_log["ret"].dropna()
        total_trades = len(returns)
        if total_trades == 0:
            return {}

        win_rate = (returns > 0).sum() / total_trades
        mean_return = returns.mean()
        median_return = returns.median()
        max_return = returns.max()
        min_return = returns.min()

        win_returns = returns[returns > 0]
        loss_returns = returns[returns < 0]
        if len(loss_returns) > 0:
            avg_win = win_returns.mean() if len(win_returns) > 0 else 0
            avg_loss = abs(loss_returns.mean())
            profit_loss_ratio = avg_win / avg_loss if avg_loss != 0 else np.inf
        else:
            profit_loss_ratio = np.inf

        # 最大回撤
        equity = equity_curve["capital"]
        cummax = equity.cummax()
        drawdown = (equity - cummax) / cummax
        max_dd = drawdown.min()

        # 简易夏普比率（假设无风险利率为0）
        daily_rets = equity_curve["portfolio_return"]
        if daily_rets.std() != 0:
            sharpe = daily_rets.mean() / daily_rets.std() * np.sqrt(252 / len(daily_rets))
        else:
            sharpe = 0.0

        return {
            "total_trades": total_trades,
            "win_rate": win_rate,
            "mean_return": mean_return,
            "median_return": median_return,
            "max_return": max_return,
            "min_return": min_return,
            "profit_loss_ratio": profit_loss_ratio,
            "max_drawdown": max_dd,
            "sharpe_ratio": sharpe,
        }