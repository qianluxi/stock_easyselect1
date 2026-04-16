"""
交易日历管理
提供 A 股交易日历的获取、缓存和常用日期计算
支持自动增量更新，确保最新交易日始终可用
"""

import pandas as pd
from typing import List, Optional, Union
from datetime import datetime, timedelta

from data.sources import TushareSource
from config import TS_TOKEN
from db.database import SQLiteDB


class TradingCalendar:
    """A股交易日历"""

    def __init__(self, db_path: str = "db/stock.db"):
        """
        初始化交易日历

        Parameters
        ----------
        db_path : str
            数据库文件路径，用于缓存交易日历数据
        """
        self.db_path = db_path
        self.source = TushareSource(TS_TOKEN)
        self._calendar_df: Optional[pd.DataFrame] = None

    def _ensure_calendar_loaded(self):
        """确保交易日历已加载到内存，并自动增量更新至今日"""
        if self._calendar_df is not None:
            # 若已加载，直接返回（可增加自动更新检查，但多数场景下无需频繁更新）
            return

        db = SQLiteDB(self.db_path)
        db.connect()
        df_cache = db.query("SELECT * FROM trading_calendar ORDER BY cal_date")
        db.close()

        # 若数据库有缓存，先加载
        if not df_cache.empty:
            df_cache["cal_date"] = pd.to_datetime(df_cache["cal_date"])
            df_cache["is_open"] = df_cache["is_open"].astype(bool)
            self._calendar_df = df_cache

            # 检查是否需要增量更新（缓存最新日期是否早于今天）
            latest_cached = self._calendar_df["cal_date"].max()
            today = pd.Timestamp(datetime.today().date())
            if latest_cached < today:
                self._update_calendar_incremental(latest_cached + timedelta(days=1), today)
        else:
            # 无缓存，执行全量拉取（从 1990 年至今天）
            print("[Calendar] 首次初始化，正在从 Tushare 获取交易日历...")
            self._fetch_and_save_full_calendar("19900101", datetime.today().strftime("%Y%m%d"))

    def _fetch_and_save_full_calendar(self, start_date: str, end_date: str):
        """全量拉取并保存日历数据"""
        df = self.source.fetch_trade_calendar(
            start_date=start_date,
            end_date=end_date,
            exchange="SSE"  # 上交所日历覆盖全市场
        )
        if df.empty:
            raise RuntimeError("无法获取交易日历数据，请检查网络或 Tushare 配置")

        df["cal_date"] = pd.to_datetime(df["cal_date"], format="%Y%m%d")
        df["is_open"] = df["is_open"].astype(bool)
        df = df.sort_values("cal_date").reset_index(drop=True)

        # 存入数据库
        db = SQLiteDB(self.db_path)
        db.connect()
        db.execute("""
            CREATE TABLE IF NOT EXISTS trading_calendar (
                cal_date TEXT PRIMARY KEY,
                is_open INTEGER,
                pretrade_date TEXT
            )
        """)
        data = [
            (row["cal_date"].strftime("%Y-%m-%d"), int(row["is_open"]), row.get("pretrade_date"))
            for _, row in df.iterrows()
        ]
        db.executemany(
            "INSERT OR REPLACE INTO trading_calendar (cal_date, is_open, pretrade_date) VALUES (?, ?, ?)",
            data
        )
        db.close()

        self._calendar_df = df

    def _update_calendar_incremental(self, start_dt: pd.Timestamp, end_dt: pd.Timestamp):
        """
        增量更新日历数据：拉取 [start_dt, end_dt] 区间内的新交易日并合并
        """
        start_str = start_dt.strftime("%Y%m%d")
        end_str = end_dt.strftime("%Y%m%d")
        print(f"[Calendar] 增量更新交易日历: {start_str} ~ {end_str}")

        df_new = self.source.fetch_trade_calendar(
            start_date=start_str,
            end_date=end_str,
            exchange="SSE"
        )
        if df_new.empty:
            # 无新交易日（例如区间内都是节假日）
            return

        df_new["cal_date"] = pd.to_datetime(df_new["cal_date"], format="%Y%m%d")
        df_new["is_open"] = df_new["is_open"].astype(bool)
        df_new = df_new.sort_values("cal_date").reset_index(drop=True)

        # 合并到内存缓存
        if self._calendar_df is not None:
            self._calendar_df = pd.concat([self._calendar_df, df_new], ignore_index=True)
            self._calendar_df = self._calendar_df.drop_duplicates(subset=["cal_date"]).sort_values("cal_date")
        else:
            self._calendar_df = df_new

        # 增量插入数据库
        db = SQLiteDB(self.db_path)
        db.connect()
        data = [
            (row["cal_date"].strftime("%Y-%m-%d"), int(row["is_open"]), row.get("pretrade_date"))
            for _, row in df_new.iterrows()
        ]
        db.executemany(
            "INSERT OR REPLACE INTO trading_calendar (cal_date, is_open, pretrade_date) VALUES (?, ?, ?)",
            data
        )
        db.close()

    def get_trading_days(
        self,
        start_date: Union[str, datetime],
        end_date: Union[str, datetime]
    ) -> List[datetime]:
        """
        获取指定区间内的所有交易日

        Parameters
        ----------
        start_date : str or datetime
            开始日期
        end_date : str or datetime
            结束日期

        Returns
        -------
        List[datetime]
            交易日列表（包含 start_date 和 end_date，若它们为交易日）
        """
        self._ensure_calendar_loaded()

        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)

        mask = (self._calendar_df["cal_date"] >= start) & (self._calendar_df["cal_date"] <= end)
        mask &= self._calendar_df["is_open"]

        return self._calendar_df.loc[mask, "cal_date"].tolist()

    def is_trading_day(self, date: Union[str, datetime]) -> bool:
        """判断某日期是否为交易日"""
        self._ensure_calendar_loaded()

        d = pd.to_datetime(date)
        row = self._calendar_df[self._calendar_df["cal_date"] == d]
        if row.empty:
            return False
        return bool(row.iloc[0]["is_open"])

    def prev_trading_day(self, date: Union[str, datetime]) -> datetime:
        """获取指定日期之前的最近一个交易日（不包含当天）"""
        self._ensure_calendar_loaded()

        d = pd.to_datetime(date)
        open_days = self._calendar_df[self._calendar_df["is_open"]]
        prev = open_days[open_days["cal_date"] < d]["cal_date"]
        if prev.empty:
            raise ValueError(f"在 {d} 之前没有交易日")
        return prev.iloc[-1]

    def next_trading_day(self, date: Union[str, datetime]) -> datetime:
        """获取指定日期之后的最近一个交易日（不包含当天）"""
        self._ensure_calendar_loaded()

        d = pd.to_datetime(date)
        open_days = self._calendar_df[self._calendar_df["is_open"]]
        nxt = open_days[open_days["cal_date"] > d]["cal_date"]
        if nxt.empty:
            raise ValueError(f"在 {d} 之后没有交易日")
        return nxt.iloc[0]

    def latest_trading_day(self, before_date: Optional[Union[str, datetime]] = None) -> datetime:
        """
        获取最新的交易日

        Parameters
        ----------
        before_date : str or datetime, optional
            若指定，则返回该日期之前（含）的最新交易日

        Returns
        -------
        datetime
        """
        self._ensure_calendar_loaded()

        open_days = self._calendar_df[self._calendar_df["is_open"]]
        if before_date is None:
            return open_days["cal_date"].iloc[-1]

        d = pd.to_datetime(before_date)
        mask = open_days["cal_date"] <= d
        return open_days.loc[mask, "cal_date"].iloc[-1]