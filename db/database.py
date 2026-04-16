"""
database.py

SQLite 数据库操作封装
- connect / close
- 执行 SQL
- 查询 DataFrame
- 初始化数据库
- 同步日志表管理

更新内容：
- 适配新 schema.py 中的表定义（daily_raw, data_meta, trading_calendar 等）
- 保留原有 daily_prices 和 sync_log 表的支持，确保向后兼容
- 所有原有方法行为不变
"""

import sqlite3
import pandas as pd
from db.schema import ALL_SCHEMA_SQL


class SQLiteDB:
    def __init__(self, db_path=None):
        import os
        # 强制定位到：项目根目录/db/stock.db
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.db_path = os.path.join(base_dir, "db", "stock.db")
        self.conn = None

    def connect(self):
        """建立数据库连接 + 初始化基础表"""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self.conn.execute("PRAGMA journal_mode = WAL;")
        self.conn.commit()

        # 自动初始化主表结构（包含新的 daily_raw, data_meta 等）
        self.init_db()

        # 自动创建同步日志表（兼容旧代码，新表 data_meta 已在 schema 中创建）
        self.create_sync_log_table()

    def close(self):
        if self.conn:
            self.conn.close()

    def execute(self, sql: str, params=None):
        """执行 SQL（增删改）"""
        cursor = self.conn.cursor()
        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)
        self.conn.commit()
        return cursor

    def executemany(self, sql: str, data: list):
        """批量执行（提升写入性能）"""
        cursor = self.conn.cursor()
        cursor.executemany(sql, data)
        self.conn.commit()
        return cursor

    def query(self, sql: str, params=None) -> pd.DataFrame:
        """执行查询返回 DataFrame"""
        if params:
            return pd.read_sql(sql, self.conn, params=params)
        else:
            return pd.read_sql(sql, self.conn)

    def init_db(self):
        """
        建表 + 索引
        执行 schema.py 中定义的所有表结构（包括新增的 daily_raw、data_meta 等）
        """

        cursor = self.conn.cursor()

        for sql in ALL_SCHEMA_SQL:
            cursor.execute(sql)

        self.conn.commit()

        print(f"[SQLiteDB] 数据库已初始化: {self.db_path}")

    def load_data(self, start_date: str, end_date: str):
        """
        原有方法：从 daily_prices 表加载数据
        注意：daily_prices 表在旧版本中使用，新数据模块使用 daily_raw
        此处保留兼容，不做修改
        """
        sql = """
            SELECT 
                p.symbol,
                p.trade_date,
                p.open_adj,
                p.high_adj,
                p.low_adj,
                p.close_adj,
                p.volume,
                p.amount,
                b.industry
            FROM daily_prices p
            LEFT JOIN stock_basic b
            ON substr(p.symbol, 1, 6) = b.symbol
            WHERE p.trade_date BETWEEN ? AND ?
            ORDER BY p.trade_date, p.symbol
        """
        df = self.query(sql, (start_date, end_date))
        return df

    def create_sync_log_table(self):
        """
        创建数据同步日志表（兼容旧代码）
        注意：新 schema 中已包含 data_meta 表，此处保留 sync_log 以满足现有调用
        """
        sql = """
        CREATE TABLE IF NOT EXISTS sync_log (
            symbol TEXT PRIMARY KEY,
            last_sync_date TEXT,
            row_count INTEGER,
            updated_at TEXT
        );
        """
        self.conn.execute(sql)
        self.conn.commit()

    def load_features(self, start_date, end_date):
        """原有方法：加载特征值表"""
        sql = """
        SELECT *
        FROM feature_values
        WHERE trade_date BETWEEN ? AND ?
        ORDER BY trade_date
        """
        df = pd.read_sql(sql, self.conn, params=(start_date, end_date))
        return df

    def load_prices(self, start_date, end_date):
        """原有方法：从 daily_prices 表加载收盘价"""
        sql = """
        SELECT symbol, trade_date, close_adj
        FROM daily_prices
        WHERE trade_date BETWEEN ? AND ?
        """
        df = pd.read_sql(sql, self.conn, params=(start_date, end_date))
        return df

    def load_industry(self):
        """原有方法：加载行业信息"""
        sql = """
        SELECT symbol, industry
        FROM stock_info
        """
        df = pd.read_sql(sql, self.conn)
        return df

    # ========================
    # 新增方法（供新 data 模块使用）
    # ========================

    def load_raw_data(self, symbols=None, start_date=None, end_date=None):
        """
        新增方法：从 daily_raw 表加载原始行情数据
        供 DataLoader / DataCache 内部使用
        """
        sql = "SELECT * FROM daily_raw WHERE 1=1"
        params = []

        if symbols:
            placeholders = ','.join(['?'] * len(symbols))
            sql += f" AND ts_code IN ({placeholders})"
            params.extend(symbols)

        if start_date:
            sql += " AND trade_date >= ?"
            params.append(start_date)

        if end_date:
            sql += " AND trade_date <= ?"
            params.append(end_date)

        sql += " ORDER BY ts_code, trade_date"
        return self.query(sql, params)

    def get_last_update_date(self, ts_code: str):
        """
        新增方法：从 data_meta 表获取某股票的最新更新日期
        """
        sql = "SELECT last_update_date FROM data_meta WHERE ts_code = ?"
        df = self.query(sql, (ts_code,))
        if df.empty:
            return None
        return df.iloc[0]['last_update_date']