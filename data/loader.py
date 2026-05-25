"""
统一数据加载器（优化版）
从本地缓存读取数据，支持按需合并日线、基本面、复权因子，生成统一分析用 DataFrame
"""

import pandas as pd
from typing import List, Optional, Union

from data.cache import DataCache
from data.calendar import TradingCalendar
from stock_pool import STOCK_POOL  # 默认股票池


class DataLoader:
    """数据加载器，提供清洗后的行情数据"""

    def __init__(self, db_path: str = "db/stock.db"):
        self.cache = DataCache(db_path)
        self.calendar = TradingCalendar(db_path)

    # ------------------------------------------------------------
    # 新增：统一加载接口（推荐使用）
    # ------------------------------------------------------------
    def load_unified(
        self,
        symbols: Optional[List[str]] = None,
        start_date: Optional[Union[str, pd.Timestamp]] = None,
        end_date: Optional[Union[str, pd.Timestamp]] = None,
        adjust: str = "none",
        fill_missing: bool = True,
        include_basic: bool = True,
        include_adjust_factor: bool = False,
    ) -> pd.DataFrame:
        """
        一次性加载日线、基本面、复权因子并合并为宽表。

        Parameters
        ----------
        symbols : List[str], optional
            股票代码列表，默认使用 STOCK_POOL
        start_date, end_date : str or pd.Timestamp, optional
            日期范围
        adjust : str, default "none"
            复权方式，可选 "qfq", "hfq", "none"
        fill_missing : bool, default True
            是否按交易日历填充缺失日期
        include_basic : bool, default True
            是否合并 daily_basic 表（市值、PE、PB等）
        include_adjust_factor : bool, default False
            是否保留复权因子列（通常仅用于复权计算，不需要保留）

        Returns
        -------
        pd.DataFrame
            MultiIndex (trade_date, symbol)，包含 OHLCV、amount、basic 指标及
            可选的 adj_factor 列。
        """
        if symbols is None:
            symbols = STOCK_POOL

        # 日期标准化
        start_str = pd.to_datetime(start_date).strftime("%Y-%m-%d") if start_date else None
        end_str = pd.to_datetime(end_date).strftime("%Y-%m-%d") if end_date else None

        # 1. 加载日线数据
        df = self.cache.load_raw_data(symbols, start_str, end_str)
        if df.empty:
            return pd.DataFrame()

        # 字段重命名
        df = df.rename(columns={"ts_code": "symbol", "vol": "volume"})
        if "volume" in df.columns:
            df["volume"] = df["volume"] * 100  # 手 → 股
        df["trade_date"] = pd.to_datetime(df["trade_date"])

        # 2. 合并 daily_basic（默认开启）
        if include_basic:
            df_basic = self.cache.load_daily_basic(symbols, start_str, end_str)
            if not df_basic.empty:
                df_basic = df_basic.rename(columns={"ts_code": "symbol"})
                df_basic["trade_date"] = pd.to_datetime(df_basic["trade_date"])
                # 左连接，保留所有日线数据
                df = df.merge(df_basic, on=["symbol", "trade_date"], how="left")
            else:
                print("警告：daily_basic 表为空，跳过合并。")

        # 3. 处理复权
        if adjust != "none":
            df_factor = self.cache.load_adjust_factor(symbols, start_str, end_str)
            if df_factor.empty:
                print("警告：未找到复权因子，返回未复权数据。")
            else:
                df_factor = df_factor.rename(columns={"ts_code": "symbol"})
                df_factor["trade_date"] = pd.to_datetime(df_factor["trade_date"])
                df = df.merge(df_factor, on=["symbol", "trade_date"], how="left")

                # 应用复权公式
                if adjust == "qfq":
                    for col in ["open", "high", "low", "close"]:
                        if col in df.columns:
                            df[col] = df[col] * df["adj_factor"]
                elif adjust == "hfq":
                    for col in ["open", "high", "low", "close"]:
                        if col in df.columns:
                            df[col] = df[col] / df["adj_factor"]

                # 如果不需要保留因子列，则删除
                if not include_adjust_factor:
                    df = df.drop(columns=["adj_factor"])

        # 4. 设置索引并对齐
        df = df.set_index(["trade_date", "symbol"]).sort_index()

        if fill_missing:
            df = self._fill_trading_days(df)

        return df

    # ------------------------------------------------------------
    # 原有 load_daily 方法（兼容旧代码）
    # ------------------------------------------------------------
    def load_daily(
        self,
        symbols: Optional[List[str]] = None,
        start_date: Optional[Union[str, pd.Timestamp]] = None,
        end_date: Optional[Union[str, pd.Timestamp]] = None,
        adjust: str = "none",
        fill_missing: bool = True,
        include_basic: bool = False,
    ) -> pd.DataFrame:
        """
        加载日线数据（兼容旧接口）
        如需同时使用 basic 数据，推荐直接使用 load_unified 方法。
        """
        return self.load_unified(
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            adjust=adjust,
            fill_missing=fill_missing,
            include_basic=include_basic,
            include_adjust_factor=False,  # 为保持旧行为，不返回因子列
        )

    # ------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------
    def _fill_trading_days(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        将 DataFrame 对齐到完整的交易日历，缺失交易日填充 NaN
        """
        if df.empty:
            return df

        min_date = df.index.get_level_values("trade_date").min()
        max_date = df.index.get_level_values("trade_date").max()
        all_days = self.calendar.get_trading_days(min_date, max_date)
        all_symbols = df.index.get_level_values("symbol").unique().tolist()

        new_index = pd.MultiIndex.from_product(
            [all_days, all_symbols],
            names=["trade_date", "symbol"]
        )
        return df.reindex(new_index)

    def load_adjust_factor(
        self,
        symbols: Optional[List[str]] = None,
        date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        加载复权因子数据（委托给 DataCache）
        """
        # 若未提供 symbols，则使用全部股票池
        if symbols is None:
            symbols = STOCK_POOL
        start = end = date if date else None
        return self.cache.load_adjust_factor(symbols, start, end)