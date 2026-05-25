"""
策略运行器（增强版：自动处理列间比较，补齐关键列）
"""
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional
from core.filter_engine import FilterEngine
from core.factor_engine import FactorEngine
from data.loader import DataLoader
from data.calendar import TradingCalendar


class StrategyRunner:
    """执行一个完整的策略流水线"""

    def __init__(self, db_path: str):
        self.loader = DataLoader(db_path)
        self.calendar = TradingCalendar(db_path)
        self.filter_engine = FilterEngine()

    def run(self, config: Dict[str, Any]) -> pd.DataFrame:
        # 1. 日期范围
        end_date = config.get("end_date", self.calendar.latest_trading_day().strftime("%Y-%m-%d"))
        window = config.get("window", 1)
        all_days = self.calendar.get_trading_days('20000101', end_date)
        if len(all_days) >= window:
            start_date = all_days[-window].strftime("%Y-%m-%d")
        else:
            start_date = all_days[0].strftime("%Y-%m-%d") if all_days else end_date

        # 2. 加载数据
        df = self.loader.load_unified(
            symbols=self._get_pool(),
            start_date=start_date,
            end_date=end_date,
            include_basic=True,
            adjust='none',
            fill_missing=False
        )
        if df.empty:
            return pd.DataFrame()

        # 3. 统一列名
        df = df.reset_index()
        if 'symbol' in df.columns:
            df.rename(columns={'symbol': 'ts_code'}, inplace=True)
        if 'volume' in df.columns and 'vol' not in df.columns:
            df.rename(columns={'volume': 'vol'}, inplace=True)

        # 3.1 确保 turnover_rate 列存在（即使 daily_basic 无数据）
        if 'turnover_rate' not in df.columns:
            df['turnover_rate'] = np.nan

        # 4. 计算因子
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
            # 分离简单条件和列间条件
            simple_filters = []
            for cond in filters:
                col, op, val = cond
                # 如果 val 是字符串且存在于 df 列中 → 列间比较
                if isinstance(val, str) and val in df.columns:
                    # 直接生成布尔 mask 并过滤 df
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
                    # 普通比较：值可能是数字或字符串，转为数字再传给 FilterEngine
                    try:
                        numeric_val = float(val)
                        simple_filters.append((col, op, numeric_val))
                    except ValueError:
                        simple_filters.append((col, op, val))
            # 对剩余简单条件使用 FilterEngine
            if simple_filters:
                df = self.filter_engine.apply_conditions(df, simple_filters)

        # 7. 涨停过滤
        exclude_limit_up = config.get("exclude_limit_up")
        if exclude_limit_up and not df.empty:
            if 'pct_chg' in df.columns:
                if exclude_limit_up == 'all':
                    df = df[df['pct_chg'] < 9.8]
                elif exclude_limit_up == 'strict':
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

    def _get_pool(self):
        try:
            from stock_pool import STOCK_POOL
            return STOCK_POOL
        except ImportError:
            return []