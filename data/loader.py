"""
统一数据加载器
从本地缓存读取数据，并进行复权、填充、对齐等标准化处理
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

    def load_daily(
        self,
        symbols: Optional[List[str]] = None,
        start_date: Optional[Union[str, pd.Timestamp]] = None,
        end_date: Optional[Union[str, pd.Timestamp]] = None,
        adjust: str = "none",
        fill_missing: bool = True,
        include_basic: bool = False   # 新增
    ) -> pd.DataFrame:
        """
        加载日线数据，返回标准化 DataFrame

        Parameters
        ----------
        symbols : List[str], optional
            股票代码列表，默认使用 stock_pool.STOCK_POOL
        start_date : str or pd.Timestamp, optional
            开始日期
        end_date : str or pd.Timestamp, optional
            结束日期
        adjust : str, default "none"
            复权方式，可选 "qfq"(前复权)、"hfq"(后复权)、"none"(不复权)
            复权因子来自 adjust_factor 表，若缺失则降级为不复权
        fill_missing : bool, default True
            是否将非交易日填充为 NaN（按交易日历对齐）

        Returns
        -------
        pd.DataFrame
            MultiIndex DataFrame，索引为 (trade_date, symbol)
            包含字段：open, high, low, close, volume, amount 等
        """
        if symbols is None:
            symbols = STOCK_POOL

        # 日期处理
        if start_date:
            start_str = pd.to_datetime(start_date).strftime("%Y-%m-%d")
        else:
            start_str = None
        if end_date:
            end_str = pd.to_datetime(end_date).strftime("%Y-%m-%d")
        else:
            end_str = None

        # 从缓存读取原始日线数据
        df_raw = self.cache.load_raw_data(symbols, start_str, end_str)
        if df_raw.empty:
            return pd.DataFrame()

        # 字段重命名与标准化
        df = df_raw.rename(columns={
            "ts_code": "symbol",
            "vol": "volume",
        })

        # 成交量单位：手 → 股
        if "volume" in df.columns:
            df["volume"] = df["volume"] * 100

        # 统一日期格式为 datetime，便于后续合并与索引
        df["trade_date"] = pd.to_datetime(df["trade_date"])

        # ---------- 复权处理 ----------
        if adjust != "none":
            # 从复权因子表读取数据
            df_factor = self.cache.load_adjust_factor(symbols, start_str, end_str)

            if df_factor.empty:
                print("警告：未在 adjust_factor 表中找到复权因子，将返回不复权数据。")
            else:
                # 统一字段名与日期类型
                df_factor = df_factor.rename(columns={"ts_code": "symbol"})
                df_factor["trade_date"] = pd.to_datetime(df_factor["trade_date"])

                # 左连接复权因子
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

                # 可选：删除 adj_factor 列以保持输出整洁
                df = df.drop(columns=["adj_factor"])

        # ---------- 设置 MultiIndex ----------
        df = df.set_index(["trade_date", "symbol"]).sort_index()

        # ---------- 对齐交易日历 ----------
        if fill_missing:
            df = self._fill_trading_days(df)
            
        # 在返回前，若 include_basic=True，则合并 daily_basic 数据
        if include_basic:
            df_basic = self.cache.load_daily_basic(symbols, start_str, end_str)
            if not df_basic.empty:
                df_basic = df_basic.rename(columns={"ts_code": "symbol"})
                df_basic["trade_date"] = pd.to_datetime(df_basic["trade_date"])
                df = df.reset_index().merge(
                    df_basic,
                    on=["symbol", "trade_date"],
                    how="left"
                ).set_index(["trade_date", "symbol"]).sort_index()
            else:
                print("警告：未找到 daily_basic 数据")

        return df

    def _fill_trading_days(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        将 DataFrame 对齐到完整的交易日历，缺失交易日填充 NaN
        """
        if df.empty:
            return df

        # 获取日期范围
        min_date = df.index.get_level_values("trade_date").min()
        max_date = df.index.get_level_values("trade_date").max()
        all_days = self.calendar.get_trading_days(min_date, max_date)
        all_symbols = df.index.get_level_values("symbol").unique().tolist()

        # 创建完整索引
        new_index = pd.MultiIndex.from_product(
            [all_days, all_symbols],
            names=["trade_date", "symbol"]
        )

        df_filled = df.reindex(new_index)
        return df_filled

    def load_adjust_factor(
        self,
        symbols: Optional[List[str]] = None,
        date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        加载复权因子数据（用于外部复权计算）

        Parameters
        ----------
        symbols : List[str], optional
        date : str, optional
            指定日期

        Returns
        -------
        pd.DataFrame
        """
        # 注意：当前缓存表 daily_raw 可能没有 adj_factor 字段
        # 该函数预留，需要时可通过 TushareSource 实时获取或扩展缓存表
        raise NotImplementedError("复权因子加载功能尚未实现，请扩展 daily_raw 表或实时获取")