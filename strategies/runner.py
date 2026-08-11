"""
策略运行器（增强版：支持股票/ETF 双池，自动处理列间比较，补齐关键列）
新增：通过 config.USE_RET40_FILTER 全局控制 ret_40 过滤的启用/禁用
"""
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional
from core.filter_engine import FilterEngine
from core.factor_engine import FactorEngine
from data.loader import DataLoader
from data.calendar import TradingCalendar
from strategies.configs import USE_RET40_FILTER  # 全局开关


class StrategyRunner:
    """执行一个完整的策略流水线，支持股票和 ETF"""

    def __init__(self, db_path: str, pool_type: str = "stock"):
        self.loader = DataLoader(db_path)
        self.calendar = TradingCalendar(db_path)
        self.filter_engine = FilterEngine()
        self.default_pool_type = pool_type

    @staticmethod
    def _limit_up_threshold(ts_code: str) -> float:
        """
        按板块返回涨停判定阈值（留 0.2 个点的缓冲，用于过滤已涨停的股票）
        - 北交所：30%（43/83/87/92 开头）
        - 创业板（300/301.SZ）、科创板（688/689.SH）：20%
        - 其余沪深主板：10%
        - ETF 默认按 10% 处理（科创/创业板 ETF 为 20%，此处不细分）
        """
        code = str(ts_code).upper()
        if code.endswith(".BJ") or code.startswith(("4", "8", "92")):
            return 29.8
        if (code.startswith(("300", "301")) and code.endswith(".SZ")) or (
            code.startswith(("688", "689")) and code.endswith(".SH")
        ):
            return 19.8
        return 9.8

    def run(self, config: Dict[str, Any]) -> pd.DataFrame:
        # 0. 确定池类型
        pool_type = config.get("pool_type", self.default_pool_type)

        # 1. 日期范围
        end_date = config.get("end_date", self.calendar.latest_trading_day().strftime("%Y-%m-%d"))
        window = config.get("window", 1)
        load_window = max(window, 80)  # 确保足够计算 ret_40
        all_days = self.calendar.get_trading_days('20000101', end_date)
        if len(all_days) >= load_window:
            start_date = all_days[-load_window].strftime("%Y-%m-%d")
        else:
            start_date = all_days[0].strftime("%Y-%m-%d") if all_days else end_date

        # 2. 加载数据
        df = self.loader.load_unified(
            symbols=self._get_pool(pool_type),
            start_date=start_date,
            end_date=end_date,
            include_basic=True,
            adjust='none',
            fill_missing=False,
            pool_type=pool_type
        )
        if df.empty:
            return pd.DataFrame()

        # 3. 统一列名
        df = df.reset_index()
        if 'symbol' in df.columns:
            df.rename(columns={'symbol': 'ts_code'}, inplace=True)
        if 'volume' in df.columns and 'vol' not in df.columns:
            df.rename(columns={'volume': 'vol'}, inplace=True)
        if 'turnover_rate' not in df.columns:
            df['turnover_rate'] = np.nan

        # 填充收盘价，消除停牌导致的缺失，保证收益率因子可计算
        df['close'] = df.groupby('ts_code')['close'].ffill()

        # 4. 计算因子
        factor_list = config.get("factors", [])
        if factor_list:
            df = FactorEngine.compute_factors(df, factor_list)

        # 5. keep_last_only
        if config.get("keep_last_only", False):
            df = df.sort_values(["ts_code", "trade_date"])
            df = df.groupby("ts_code").tail(1)

        # 6. 获取过滤条件
        filters = config.get("filters", [])

        # 全局开关：若禁用 ret_40 过滤，则移除所有 ret_40 条件
        if not USE_RET40_FILTER:
            filters = [cond for cond in filters if cond[0] != "ret_40"]

        # 7. 清理无法计算 ret 因子的股票（避免 NaN 导致过滤失效）
        for cond in filters:
            col = cond[0]
            if col.startswith('ret_') and col in df.columns:
                before = len(df)
                df = df.dropna(subset=[col])
                after = len(df)
                if after < before:
                    print(f"[{config.get('name', '策略')}] 因 {col} 为 NaN，剔除 {before - after} 只股票")

        # 8. 处理过滤条件（支持列间比较）
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

        # 9. 涨停过滤
        exclude_limit_up = config.get("exclude_limit_up")
        if exclude_limit_up and not df.empty:
            if 'pct_chg' in df.columns and 'ts_code' in df.columns:
                threshold = df['ts_code'].map(self._limit_up_threshold)
                df = df[df['pct_chg'] < threshold]
            else:
                print("警告：缺少 'pct_chg' 或 'ts_code' 列，涨停过滤跳过")

        # 10. 排序取前 N
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
