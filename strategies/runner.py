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

    # 添加在 StrategyRunner 类内部（例如放在 __init__ 之后）
    @staticmethod
    def apply_quality_filters(df: pd.DataFrame, remove_risky: bool = True, prefer_healthy: bool = True) -> pd.DataFrame:
        """
        对筛选结果进行二次质量过滤

        Parameters
        ----------
        df : pd.DataFrame
            原始筛选结果
        remove_risky : bool
            是否剔除明显风险标的（如 PE 异常、亏损等）
        prefer_healthy : bool
            是否进一步优选量价健康个股（换手率温和、量比适中、PE合理等）

        Returns
        -------
        pd.DataFrame
            过滤后的 DataFrame
        """
        if df.empty:
            return df

        result = df.copy()

        # ---------- 1. 剔除明显风险标的 ----------
        if remove_risky:
            # 剔除 PE(TTM) 为 NaN 或 > 200 的股票（可根据市场调整）
            if "pe_ttm" in result.columns:
                result = result[result["pe_ttm"].notna()]
                result = result[result["pe_ttm"] < 200]

            # 剔除 ST、*ST 股票（代码中包含 .ST）
            result = result[~result["ts_code"].str.contains(".ST", na=False)]

            # 剔除流通市值过小（< 20 亿，即 200000 万元）
            if "circ_mv" in result.columns:
                result = result[result["circ_mv"] >= 200000]

        # ---------- 2. 优选量价健康个股（保留满足条件的行） ----------
        if prefer_healthy:
            if "turnover" in result.columns:
                # 换手率 5% ~ 12% 为温和区间
                result = result[(result["turnover"] >= 5.0) & (result["turnover"] <= 12.0)]
            if "volume_ratio" in result.columns:
                # 量比 1.5 ~ 3.5 为健康放量
                result = result[(result["volume_ratio"] >= 1.5) & (result["volume_ratio"] <= 3.5)]
            if "pe_ttm" in result.columns:
                # PE 在 20 ~ 50 倍之间较为合理
                result = result[(result["pe_ttm"] >= 20) & (result["pe_ttm"] <= 50)]

        return result    

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

        # ---------- 后处理：应用质量过滤（若配置中启用） ----------
        if config.get("apply_quality_filter", False):
            df = self.apply_quality_filters(df, 
                                            remove_risky=config.get("remove_risky", True),
                                            prefer_healthy=config.get("prefer_healthy", True))
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

        # ---------- 后处理：应用质量过滤（若配置中启用） ----------
        if config.get("apply_quality_filter", False):
            df = self.apply_quality_filters(df, 
                                            remove_risky=config.get("remove_risky", True),
                                            prefer_healthy=config.get("prefer_healthy", True))
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