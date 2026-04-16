"""
数据加载层
支持单日数据和多日时间窗口数据的加载
"""

import sqlite3
from pathlib import Path
from typing import Optional, List, Union
import pandas as pd


class DataLoader:
    """股票数据加载器，基于 SQLite 数据库"""

    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f"数据库文件不存在: {self.db_path}")

    def _get_connection(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def get_latest_trade_date(self) -> Optional[str]:
        """获取 daily_raw 表中最近一个交易日期"""
        query = "SELECT MAX(trade_date) FROM daily_raw"
        with self._get_connection() as conn:
            cursor = conn.execute(query)
            latest = cursor.fetchone()[0]
        return latest

    def load_daily(
        self,
        trade_date: Optional[str] = None,
        ts_codes: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        加载单日数据，关联 daily_basic 表

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

        query = """
            SELECT
                r.ts_code,
                r.trade_date,
                r.open,
                r.high,
                r.low,
                r.close,
                r.pre_close,
                r.change,
                r.pct_chg,
                r.vol,
                r.amount,
                b.total_mv,
                b.circ_mv,
                b.turnover_rate,
                b.turnover_rate_f,
                b.volume_ratio,
                b.pe,
                b.pe_ttm,
                b.pb
            FROM daily_raw r
            LEFT JOIN daily_basic b
                ON r.ts_code = b.ts_code AND r.trade_date = b.trade_date
            WHERE r.trade_date = ?
        """
        params = [trade_date]

        if ts_codes:
            placeholders = ",".join(["?"] * len(ts_codes))
            query += f" AND r.ts_code IN ({placeholders})"
            params.extend(ts_codes)

        with self._get_connection() as conn:
            df = pd.read_sql_query(query, conn, params=params)

        # 处理换手率：优先使用自由流通换手率
        df["turnover"] = df["turnover_rate_f"].fillna(df["turnover_rate"])
        return df

    def load_window(
        self,
        start_date: str,
        end_date: str,
        ts_codes: Optional[List[str]] = None,
        include_basic: bool = True,
    ) -> pd.DataFrame:
        """
        加载多日时间窗口数据（核心新增方法）

        Parameters
        ----------
        start_date : str
            起始日期 (YYYY-MM-DD)
        end_date : str
            结束日期 (YYYY-MM-DD)
        ts_codes : List[str], optional
            指定股票代码列表，默认全部
        include_basic : bool, default True
            是否关联 daily_basic 表

        Returns
        -------
        pd.DataFrame
            多股票 × 多日期的面板数据，按 ts_code 和 trade_date 排序
        """
        if include_basic:
            query = """
                SELECT
                    r.ts_code,
                    r.trade_date,
                    r.open,
                    r.high,
                    r.low,
                    r.close,
                    r.pre_close,
                    r.change,
                    r.pct_chg,
                    r.vol,
                    r.amount,
                    b.total_mv,
                    b.circ_mv,
                    b.turnover_rate,
                    b.turnover_rate_f,
                    b.volume_ratio,
                    b.pe,
                    b.pe_ttm,
                    b.pb
                FROM daily_raw r
                LEFT JOIN daily_basic b
                    ON r.ts_code = b.ts_code AND r.trade_date = b.trade_date
                WHERE r.trade_date BETWEEN ? AND ?
            """
        else:
            query = """
                SELECT
                    r.ts_code,
                    r.trade_date,
                    r.open,
                    r.high,
                    r.low,
                    r.close,
                    r.pre_close,
                    r.change,
                    r.pct_chg,
                    r.vol,
                    r.amount
                FROM daily_raw r
                WHERE r.trade_date BETWEEN ? AND ?
            """

        params = [start_date, end_date]

        if ts_codes:
            placeholders = ",".join(["?"] * len(ts_codes))
            query += f" AND r.ts_code IN ({placeholders})"
            params.extend(ts_codes)

        query += " ORDER BY r.ts_code, r.trade_date"

        with self._get_connection() as conn:
            df = pd.read_sql_query(query, conn, params=params)

        if include_basic:
            df["turnover"] = df["turnover_rate_f"].fillna(df["turnover_rate"])

        return df