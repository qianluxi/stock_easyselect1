"""
策略运行器（增强版：支持股票/ETF 双池，自动处理列间比较，补齐关键列）
"""
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional
from core.filter_engine import FilterEngine
from core.factor_engine import FactorEngine
from data.loader import DataLoader
from data.calendar import TradingCalendar


class StrategyRunner:
    """执行一个完整的策略流水线，支持股票和 ETF"""

    def __init__(self, db_path: str, pool_type: str = "stock"):
        """
        Parameters
        ----------
        db_path : str
            数据库路径
        pool_type : str, default 'stock'
            默认池类型，可选 'stock' 或 'etf'
        """
        self.loader = DataLoader(db_path)
        self.calendar = TradingCalendar(db_path)
        self.filter_engine = FilterEngine()
        self.default_pool_type = pool_type    # 保存默认池类型

    def run(self, config: Dict[str, Any]) -> pd.DataFrame:
        """
        执行策略

        可通过 config 中的 'pool_type' 键覆盖默认池类型，
        例如 config['pool_type'] = 'etf'
        """
        # 0. 确定本次运行的池类型（策略配置优先，否则用默认）
        pool_type = config.get("pool_type", self.default_pool_type)

        # 1. 日期范围
        end_date = config.get("end_date", self.calendar.latest_trading_day().strftime("%Y-%m-%d"))
        window = config.get("window", 1)
        # 实际加载天数：取 window 和 30 的较大值，确保有足够历史数据计算各种周期因子
        load_window = max(window, 30)
        all_days = self.calendar.get_trading_days('20000101', end_date)
        if len(all_days) >= load_window:
            start_date = all_days[-load_window].strftime("%Y-%m-%d")
        else:
            start_date = all_days[0].strftime("%Y-%m-%d") if all_days else end_date

        # 2. 加载数据（传递 pool_type）
        df = self.loader.load_unified(
            symbols=self._get_pool(pool_type),
            start_date=start_date,
            end_date=end_date,
            include_basic=True,          # ETF 会自动跳过 basic 合并
            adjust='none',
            fill_missing=False,
            pool_type=pool_type          # 关键：告诉 loader 用哪张表
        )
        if df.empty:
            return pd.DataFrame()

        # 3. 统一列名
        df = df.reset_index()
        if 'symbol' in df.columns:
            df.rename(columns={'symbol': 'ts_code'}, inplace=True)
        if 'volume' in df.columns and 'vol' not in df.columns:
            df.rename(columns={'volume': 'vol'}, inplace=True)

        # 3.1 确保 turnover_rate 列存在（ETF 数据中没有，补 NaN）
        if 'turnover_rate' not in df.columns:
            df['turnover_rate'] = np.nan

        # 4. 计算因子（量价因子对 ETF 同样有效）
        factor_list = config.get("factors", [])
        if factor_list:
            df = FactorEngine.compute_factors(df, factor_list)


        # 5. keep_last_only
        if config.get("keep_last_only", False):
            df = df.sort_values(["ts_code", "trade_date"])
            df = df.groupby("ts_code").tail(1)

        # 6. 处理过滤条件（支持列间比较）
        filters = config.get("filters", [])
        if filters:
            simple_filters = []
            for cond in filters:
                col, op, val = cond
                # 列间比较
                if isinstance(val, str) and val in df.columns:
                    if op == ">":
                        df = df[df[col] > df[val]]
                    elif op == "<":
                        df = df[df[col] < df[val]]
                    elif op == ">=":
                        df = df[df[col] >= df[val]]
                    elif op == "<=":
                        df = df[df[col] <= df[val]]
                    elif op == "==":
                        df = df[df[col] == df[val]]
                    elif op == "!=":
                        df = df[df[col] != df[val]]
                    else:
                        print(f"警告: 不支持的列间比较操作符 '{op}'，已跳过")
                else:
                    # 普通比较
                    try:
                        numeric_val = float(val)
                        simple_filters.append((col, op, numeric_val))
                    except ValueError:
                        simple_filters.append((col, op, val))
            if simple_filters:
                df = self.filter_engine.apply_conditions(df, simple_filters)

        # 7. 涨停过滤（ETF 同样适用，但阈值可适当放宽）
        exclude_limit_up = config.get("exclude_limit_up")
        if exclude_limit_up and not df.empty:
            if 'pct_chg' in df.columns:
                # ETF 涨跌停幅度通常也是 10% 或 20%，这里统一用 9.8 过滤
                if exclude_limit_up == 'all' or exclude_limit_up == 'strict':
                    df = df[df['pct_chg'] < 9.8]
            else:
                print("警告：缺少 'pct_chg' 列，涨停过滤跳过")

        # 8. 排序取前 N
        sort_by = config.get("sort_by")
        if sort_by and sort_by in df.columns:
            ascending = config.get("ascending", True)
            df = df.sort_values(sort_by, ascending=ascending)
        top_n = config.get("top_n")
        if top_n and len(df) > top_n:
            df = df.head(top_n)

        return df

    def _get_pool(self, pool_type: str = "stock"):
        """根据池类型返回对应的股票/ETF 列表"""
        if pool_type == "etf":
            try:
                from etf_pool import ETF_POOL
                return ETF_POOL
            except ImportError:
                print("警告：未找到 etf_pool.py，ETF 池为空")
                return []
        else:
            try:
                from stock_pool import STOCK_POOL
                return STOCK_POOL
            except ImportError:
                return []