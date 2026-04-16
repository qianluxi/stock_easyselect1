"""
数据源抽象基类
定义了所有数据源必须实现的接口
"""

from abc import ABC, abstractmethod
from typing import List, Optional
import pandas as pd


class DataSource(ABC):
    """数据源抽象基类"""

    @abstractmethod
    def fetch_daily(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        **kwargs
    ) -> pd.DataFrame:
        """
        获取日线行情数据

        Parameters
        ----------
        symbols : List[str]
            股票代码列表，如 ['000001.SZ', '600000.SH']
        start_date : str
            开始日期，格式 YYYYMMDD 或 YYYY-MM-DD
        end_date : str
            结束日期，格式 YYYYMMDD 或 YYYY-MM-DD
        **kwargs
            其他数据源特定参数

        Returns
        -------
        pd.DataFrame
            包含以下字段的 DataFrame：
            - symbol / ts_code : 股票代码
            - trade_date : 交易日期
            - open, high, low, close : 开高低收
            - pre_close, change, pct_chg : 前收/涨跌额/涨跌幅
            - vol : 成交量（手）
            - amount : 成交额（千元）
            - total_mv : 总市值（万元）
            - turnover_rate : 换手率（%）
        """
        pass

    @abstractmethod
    def fetch_adjust_factor(
        self,
        trade_date: Optional[str] = None,
        symbols: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """
        获取复权因子

        Parameters
        ----------
        trade_date : str, optional
            指定交易日期，格式 YYYYMMDD
        symbols : List[str], optional
            股票代码列表，若不指定则返回全部

        Returns
        -------
        pd.DataFrame
            包含字段：ts_code, trade_date, adj_factor
        """
        pass

    @abstractmethod
    def fetch_trade_calendar(
        self,
        start_date: str,
        end_date: str,
        exchange: str = "SSE"
    ) -> pd.DataFrame:
        """
        获取交易日历

        Parameters
        ----------
        start_date : str
            开始日期，格式 YYYYMMDD
        end_date : str
            结束日期，格式 YYYYMMDD
        exchange : str
            交易所，默认 "SSE"（上交所），可选 "SZSE"（深交所）、"BSE"（北交所）

        Returns
        -------
        pd.DataFrame
            包含字段：cal_date, is_open, pretrade_date
        """
        pass