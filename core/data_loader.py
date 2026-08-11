"""
数据加载层（统一版）

核心加载逻辑已统一到 data/loader.py（load_unified），本模块保留旧接口
（load_daily / load_window / get_latest_trade_date）作为兼容包装，
供回测器使用，避免两套加载逻辑并存。
"""

import sqlite3
from pathlib import Path
from typing import Optional, List, Union
import pandas as pd

from data.loader import DataLoader as UnifiedDataLoader


class DataLoader:
    """股票数据加载器（兼容旧接口，内部复用 data/loader.py 的统一加载）"""

    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f"数据库文件不存在: {self.db_path}")
        self._unified = UnifiedDataLoader(str(self.db_path))

    def _get_connection(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def get_latest_trade_date(self) -> Optional[str]:
        """获取 daily_raw 表中最近一个交易日期"""
        query = "SELECT MAX(trade_date) FROM daily_raw"
        with self._get_connection() as conn:
            cursor = conn.execute(query)
            latest = cursor.fetchone()[0]
        return latest

    @staticmethod
    def _normalize(df: pd.DataFrame) -> pd.DataFrame:
        """
        将统一加载器输出转为旧接口格式：
        MultiIndex -> 平铺、symbol -> ts_code、volume(股) -> vol(手)、
        trade_date 转回字符串（与数据库 TEXT 格式一致）、补充 turnover 列。
        """
        if df.empty:
            return df

        df = df.reset_index()
        if "symbol" in df.columns:
            df = df.rename(columns={"symbol": "ts_code"})
        if "volume" in df.columns:
            df["vol"] = df["volume"] / 100  # 股 → 手（与 Tushare 原始单位一致）
            df = df.drop(columns=["volume"])
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
        df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

        if "turnover_rate_f" in df.columns and "turnover_rate" in df.columns:
            df["turnover"] = df["turnover_rate_f"].fillna(df["turnover_rate"])
        elif "turnover_rate" in df.columns:
            df["turnover"] = df["turnover_rate"]
        return df

    def load_daily(
        self,
        trade_date: Optional[str] = None,
        ts_codes: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        加载单日数据（含 daily_basic 字段）

        Parameters
        ----------
        trade_date : str, optional
            交易日期 (YYYY-MM-DD)，默认最新
        ts_codes : List[str], optional
            指定股票代码列表，默认全部

        Returns
        -------
        pd.DataFrame
            包含日线行情和基本面字段的 DataFrame
        """
        if trade_date is None:
            trade_date = self.get_latest_trade_date()
            if trade_date is None:
                raise ValueError("数据库中没有 daily_raw 数据")

        df = self._unified.load_unified(
            symbols=ts_codes,
            start_date=trade_date,
            end_date=trade_date,
            include_basic=True,
            fill_missing=False,
        )
        return self._normalize(df)

    def load_window(
        self,
        start_date: str,
        end_date: str,
        ts_codes: Optional[List[str]] = None,
        include_basic: bool = True,
    ) -> pd.DataFrame:
        """
        加载多日时间窗口数据（核心方法）

        Parameters
        ----------
        start_date : str
            起始日期 (YYYY-MM-DD)
        end_date : str
            结束日期 (YYYY-MM-DD)
        ts_codes : List[str], optional
            指定股票代码列表，默认全部
        include_basic : bool, default True
            是否合并 daily_basic 表

        Returns
        -------
        pd.DataFrame
            多股票 × 多日期的面板数据，按 ts_code 和 trade_date 排序
        """
        df = self._unified.load_unified(
            symbols=ts_codes,
            start_date=start_date,
            end_date=end_date,
            include_basic=include_basic,
            fill_missing=False,
        )
        return self._normalize(df)
