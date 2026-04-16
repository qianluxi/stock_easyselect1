"""
策略执行器
根据策略配置字典，调度 DataLoader、FactorEngine、FilterEngine 完成筛选
"""

import pandas as pd
from datetime import timedelta
from typing import Optional, List, Dict, Any

from core.data_loader import DataLoader
from core.factor_engine import FactorEngine
from core.filter_engine import FilterEngine


class StrategyRunner:
    """策略运行器"""

    def __init__(self, db_path: str):
        self.loader = DataLoader(db_path)
        self.factor_engine = FactorEngine()
        self.filter_engine = FilterEngine()

    def run(self, strategy_config: Dict[str, Any], ts_codes: Optional[List[str]] = None) -> pd.DataFrame:
        """
        执行策略

        Parameters
        ----------
        strategy_config : dict
            策略配置字典，必须包含：
            - name: str
            - type: 'single_day' 或 'window'
            其余字段根据类型不同而异
        ts_codes : List[str], optional
            指定股票池，默认全部

        Returns
        -------
        pd.DataFrame
            筛选结果
        """
        strategy_type = strategy_config.get("type", "window")
        if strategy_type == "single_day":
            return self._run_single_day(strategy_config, ts_codes)
        else:
            return self._run_window(strategy_config, ts_codes)

    def _run_single_day(self, config: Dict[str, Any], ts_codes: Optional[List[str]]) -> pd.DataFrame:
        """执行单日策略"""
        trade_date = config.get("trade_date")
        if trade_date is None:
            trade_date = self.loader.get_latest_trade_date()

        df = self.loader.load_daily(trade_date, ts_codes)

        # 应用过滤
        filters = config.get("filters", [])
        df = self._apply_filters_with_column_ref(df, filters)

        # 排序
        sort_by = config.get("sort_by")
        ascending = config.get("ascending", False)
        if sort_by:
            df = df.sort_values(sort_by, ascending=ascending)

        top_n = config.get("top_n")
        if top_n:
            df = df.head(top_n)

        return df

    def _run_window(self, config: Dict[str, Any], ts_codes: Optional[List[str]]) -> pd.DataFrame:
        """执行多日窗口策略"""
        name = config.get("name", "未命名策略")
        window = config.get("window", 20)
        end_date = config.get("end_date")
        if end_date is None:
            end_date = self.loader.get_latest_trade_date()

        # 计算起始日期（回退 window 个日历日，为简化此处用自然日）
        end_dt = pd.to_datetime(end_date)
        start_dt = end_dt - timedelta(days=window * 2)  # 留足缓冲
        start_date = start_dt.strftime("%Y-%m-%d")

        print(f"执行策略: {name}，数据窗口: {start_date} ~ {end_date}")

        # 1. 加载数据
        df = self.loader.load_window(start_date, end_date, ts_codes)

        # 2. 计算因子
        factors = config.get("factors", [])
        if factors:
            df = self.factor_engine.compute_factors(df, factors)

        # 3. 是否只保留最后一日
        keep_last_only = config.get("keep_last_only", True)
        if keep_last_only:
            df = df.sort_values(["ts_code", "trade_date"])
            df = df.groupby("ts_code").tail(1)

        # 4. 应用过滤
        filters = config.get("filters", [])
        df = self._apply_filters_with_column_ref(df, filters)

        # 5. 排序
        sort_by = config.get("sort_by")
        ascending = config.get("ascending", False)
        if sort_by:
            df = df.sort_values(sort_by, ascending=ascending)

        top_n = config.get("top_n")
        if top_n:
            df = df.head(top_n)

        return df

    def _apply_filters_with_column_ref(self, df: pd.DataFrame, filters: list) -> pd.DataFrame:
        """
        应用过滤条件，支持列间比较（如 ('ma_5', '>', 'ma_20')）
        """
        if not filters:
            return df.copy()
        
        # 检查所需列是否存在
        for col, op, val in filters:
            if col not in df.columns:
                raise KeyError(f"过滤条件中的列 '{col}' 不在数据中，可用列: {list(df.columns)}")
            if isinstance(val, str) and val in df.columns:
                # 列间比较，val 列也需存在
                pass  # 已通过 in df.columns 检查

        mask = pd.Series(True, index=df.index)
        for col, op, val in filters:
            # 检查 val 是否为列名（字符串且存在于 df.columns）
            if isinstance(val, str) and val in df.columns:
                # 列间比较
                if op == ">":
                    mask &= (df[col] > df[val])
                elif op == "<":
                    mask &= (df[col] < df[val])
                elif op == ">=":
                    mask &= (df[col] >= df[val])
                elif op == "<=":
                    mask &= (df[col] <= df[val])
                elif op == "==":
                    mask &= (df[col] == df[val])
                elif op == "!=":
                    mask &= (df[col] != df[val])
                else:
                    raise ValueError(f"不支持的列间比较操作符: {op}")
            else:
                # 常规常量比较
                if op == ">":
                    mask &= (df[col] > val)
                elif op == "<":
                    mask &= (df[col] < val)
                elif op == ">=":
                    mask &= (df[col] >= val)
                elif op == "<=":
                    mask &= (df[col] <= val)
                elif op == "==":
                    mask &= (df[col] == val)
                elif op == "!=":
                    mask &= (df[col] != val)
                elif op == "between":
                    if not isinstance(val, (tuple, list)) or len(val) != 2:
                        raise ValueError("'between' 值必须为二元组")
                    mask &= df[col].between(val[0], val[1])
                else:
                    raise ValueError(f"不支持的操作符: {op}")
        return df[mask].copy()