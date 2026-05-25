"""
本地数据缓存管理（批量优化版）
负责将拉取的原始数据存入 SQLite 数据库，并提供查询接口。
新增：全局最新日期管理，支持批量增量拉取。
"""

import pandas as pd
from typing import List, Optional
from datetime import datetime

from db.database import SQLiteDB


class DataCache:
    """数据缓存管理器"""

    def __init__(self, db_path: str = "db/stock.db"):
        self.db_path = db_path
        self._ensure_tables()

    def _ensure_tables(self):
        """创建必要的表结构（如果不存在）"""
        db = SQLiteDB(self.db_path)
        db.connect()

        # 原始日线表
        db.execute("""
            CREATE TABLE IF NOT EXISTS daily_raw (
                ts_code       TEXT NOT NULL,
                trade_date    TEXT NOT NULL,
                open          REAL,
                high          REAL,
                low           REAL,
                close         REAL,
                pre_close     REAL,
                change        REAL,
                pct_chg       REAL,
                vol           REAL,
                amount        REAL,
                total_mv      REAL,
                turnover_rate REAL,
                PRIMARY KEY (ts_code, trade_date)
            )
        """)

        # 复权因子表
        db.execute("""
            CREATE TABLE IF NOT EXISTS adjust_factor (
                ts_code       TEXT NOT NULL,
                trade_date    TEXT NOT NULL,
                adj_factor    REAL NOT NULL,
                PRIMARY KEY (ts_code, trade_date)
            )
        """)

        # 每日基本面指标表
        db.execute("""
            CREATE TABLE IF NOT EXISTS daily_basic (
                ts_code           TEXT NOT NULL,
                trade_date        TEXT NOT NULL,
                total_mv          REAL,
                circ_mv           REAL,
                turnover_rate     REAL,
                turnover_rate_f   REAL,
                volume_ratio      REAL,
                pe                REAL,
                pe_ttm            REAL,
                pb                REAL,
                PRIMARY KEY (ts_code, trade_date)
            )
        """)

        # 元数据表：记录每只股票的最新拉取状态，同时用 __GLOBAL__ 存全局日期
        db.execute("""
            CREATE TABLE IF NOT EXISTS data_meta (
                ts_code          TEXT PRIMARY KEY,
                last_update_date TEXT,
                row_count        INTEGER,
                updated_at       TEXT
            )
        """)

        db.close()

    # ========================
    # 全局日期管理 (新增)
    # ========================

    def get_global_last_date(self) -> Optional[str]:
        """
        获取全局最新数据日期（所有股票中最大的 trade_date）
        返回格式为 'YYYY-MM-DD' 的字符串，若库空则返回 None
        """
        db = SQLiteDB(self.db_path)
        db.connect()
        df = db.query("SELECT MAX(trade_date) as max_date FROM daily_raw")
        db.close()
        if df.empty or df.iloc[0]["max_date"] is None:
            return None
        return df.iloc[0]["max_date"]

    def set_global_last_date(self, date_val: datetime = None):
        """
        将全局最新拉取日期写入 data_meta 表（使用特殊代码 __GLOBAL__），
        方便下次增量拉取判断起点。
        """
        if date_val is None:
            date_str = datetime.now().strftime("%Y-%m-%d")
        elif isinstance(date_val, datetime):
            date_str = date_val.strftime("%Y-%m-%d")
        else:
            date_str = str(date_val)
        
        db = SQLiteDB(self.db_path)
        db.connect()
        db.execute(
            "INSERT OR REPLACE INTO data_meta (ts_code, last_update_date, row_count, updated_at) VALUES (?, ?, ?, ?)",
            ("__GLOBAL__", date_str, 0, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        db.close()

    # ========================
    # 数据写入
    # ========================

    def save_daily_batch(self, df: pd.DataFrame):
        """批量保存日线数据"""
        if df.empty:
            return

        db = SQLiteDB(self.db_path)
        db.connect()

        df = df.copy()
        if "trade_date" in df.columns:
            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")

        cols = [
            "ts_code", "trade_date", "open", "high", "low", "close",
            "pre_close", "change", "pct_chg", "vol", "amount"
        ]
        if "total_mv" in df.columns:
            cols.append("total_mv")
        if "turnover_rate" in df.columns:
            cols.append("turnover_rate")

        available_cols = [c for c in cols if c in df.columns]
        data_tuples = [tuple(row[col] for col in available_cols) for _, row in df[available_cols].iterrows()]

        placeholders = ", ".join(["?"] * len(available_cols))
        sql = f"INSERT OR REPLACE INTO daily_raw ({', '.join(available_cols)}) VALUES ({placeholders})"

        db.executemany(sql, data_tuples)
        db.close()

    def save_adjust_factor_batch(self, df: pd.DataFrame):
        """批量保存复权因子数据"""
        if df.empty:
            return

        db = SQLiteDB(self.db_path)
        db.connect()

        df = df.copy()
        if "trade_date" in df.columns:
            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")

        data = [
            (row["ts_code"], row["trade_date"], float(row["adj_factor"]))
            for _, row in df.iterrows()
        ]

        db.executemany(
            "INSERT OR REPLACE INTO adjust_factor (ts_code, trade_date, adj_factor) VALUES (?, ?, ?)",
            data
        )
        db.close()

    def save_daily_basic_batch(self, df: pd.DataFrame):
        """批量保存每日基本面指标数据"""
        if df.empty:
            return

        db = SQLiteDB(self.db_path)
        db.connect()

        df = df.copy()
        if "trade_date" in df.columns:
            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")

        possible_cols = [
            "ts_code", "trade_date", "total_mv", "circ_mv", "turnover_rate",
            "turnover_rate_f", "volume_ratio", "pe", "pe_ttm", "pb"
        ]
        available_cols = [c for c in possible_cols if c in df.columns]
        data = [tuple(row[col] for col in available_cols) for _, row in df[available_cols].iterrows()]

        placeholders = ", ".join(["?"] * len(available_cols))
        sql = f"INSERT OR REPLACE INTO daily_basic ({', '.join(available_cols)}) VALUES ({placeholders})"
        db.executemany(sql, data)
        db.close()

    def update_meta(self, ts_code: str, last_date: str, row_count: Optional[int] = None):
        """
        更新单只股票的元数据。
        若 row_count 为 None，则不更新该字段，保留原值或置空。
        """
        db = SQLiteDB(self.db_path)
        db.connect()
        
        if row_count is None:
            db.execute("""
                INSERT OR REPLACE INTO data_meta (ts_code, last_update_date, updated_at)
                VALUES (?, ?, ?)
            """, (ts_code, last_date, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        else:
            db.execute("""
                INSERT OR REPLACE INTO data_meta (ts_code, last_update_date, row_count, updated_at)
                VALUES (?, ?, ?, ?)
            """, (ts_code, last_date, row_count, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        
        db.close()

    # ========================
    # 数据读取
    # ========================

    def get_last_update_date(self, ts_code: str) -> Optional[str]:
        """获取某只股票的最新更新日期（从 data_meta 表）"""
        db = SQLiteDB(self.db_path)
        db.connect()
        df = db.query("SELECT last_update_date FROM data_meta WHERE ts_code = ?", (ts_code,))
        db.close()
        if df.empty:
            return None
        return df.iloc[0]["last_update_date"]

    def load_raw_data(
        self,
        symbols: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """从缓存加载原始日线数据"""
        db = SQLiteDB(self.db_path)
        db.connect()

        where_clauses = []
        params = []

        if symbols:
            placeholders = ", ".join(["?"] * len(symbols))
            where_clauses.append(f"ts_code IN ({placeholders})")
            params.extend(symbols)

        if start_date:
            where_clauses.append("trade_date >= ?")
            params.append(start_date)

        if end_date:
            where_clauses.append("trade_date <= ?")
            params.append(end_date)

        sql = "SELECT * FROM daily_raw"
        if where_clauses:
            sql += " WHERE " + " AND ".join(where_clauses)
        sql += " ORDER BY ts_code, trade_date"

        df = db.query(sql, tuple(params))
        db.close()

        if df.empty:
            return df

        df["trade_date"] = pd.to_datetime(df["trade_date"])
        return df

    def load_adjust_factor(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """从缓存加载复权因子"""
        db = SQLiteDB(self.db_path)
        db.connect()

        placeholders = ','.join(['?'] * len(symbols))
        sql = f"""
            SELECT ts_code, trade_date, adj_factor
            FROM adjust_factor
            WHERE ts_code IN ({placeholders})
              AND trade_date >= ?
              AND trade_date <= ?
            ORDER BY ts_code, trade_date
        """
        params = symbols + [start_date, end_date]
        df = db.query(sql, tuple(params))
        db.close()

        if not df.empty:
            df["trade_date"] = pd.to_datetime(df["trade_date"])
        return df

    def load_daily_basic(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """从缓存加载每日基本面指标数据"""
        db = SQLiteDB(self.db_path)
        db.connect()

        placeholders = ','.join(['?'] * len(symbols))
        sql = f"""
            SELECT * FROM daily_basic
            WHERE ts_code IN ({placeholders})
              AND trade_date >= ?
              AND trade_date <= ?
            ORDER BY ts_code, trade_date
        """
        params = symbols + [start_date, end_date]
        df = db.query(sql, tuple(params))
        db.close()

        if not df.empty:
            df["trade_date"] = pd.to_datetime(df["trade_date"])
        return df