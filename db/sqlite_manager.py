"""
sqlite_manager.py

轻量级 SQLite 数据库管理器
提供常用数据库操作，可替代部分 database.py 的功能
"""

import sqlite3
import pandas as pd
from typing import List, Optional, Tuple, Any


class SQLiteManager:
    """SQLite 数据库管理器"""

    def __init__(self, db_path: str):
        """
        初始化数据库连接

        Parameters
        ----------
        db_path : str
            数据库文件路径
        """
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self.conn.execute("PRAGMA journal_mode = WAL;")

    def __enter__(self):
        """上下文管理器入口"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口，自动提交并关闭连接"""
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        self.close()

    # -------------------------------
    # 事务管理
    # -------------------------------
    def commit(self):
        """提交事务"""
        self.conn.commit()

    def rollback(self):
        """回滚事务"""
        self.conn.rollback()

    def close(self):
        """关闭数据库连接"""
        if self.conn:
            self.conn.close()

    # -------------------------------
    # 表操作
    # -------------------------------
    def create_table(self, table_name: str, schema_sql: str):
        """
        创建表（如果不存在）

        Parameters
        ----------
        table_name : str
            表名
        schema_sql : str
            完整的 CREATE TABLE 语句
        """
        self.conn.execute(schema_sql)
        self.commit()

    def table_exists(self, table_name: str) -> bool:
        """检查表是否存在"""
        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,)
        )
        return cursor.fetchone() is not None

    # -------------------------------
    # 数据写入
    # -------------------------------
    def insert(self, table: str, data: dict):
        """
        插入单行数据

        Parameters
        ----------
        table : str
            表名
        data : dict
            字段名与值的映射
        """
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
        self.conn.execute(sql, tuple(data.values()))
        self.commit()

    def insert_many(self, table: str, columns: List[str], rows: List[Tuple]):
        """
        批量插入数据

        Parameters
        ----------
        table : str
            表名
        columns : List[str]
            列名列表
        rows : List[Tuple]
            数据行列表，每行是一个元组
        """
        placeholders = ", ".join(["?"] * len(columns))
        col_str = ", ".join(columns)
        sql = f"INSERT OR REPLACE INTO {table} ({col_str}) VALUES ({placeholders})"
        cursor = self.conn.cursor()
        cursor.executemany(sql, rows)
        self.commit()

    def upsert(self, table: str, data: dict, conflict_columns: List[str]):
        """
        插入或更新（ON CONFLICT 语法）

        Parameters
        ----------
        table : str
            表名
        data : dict
            字段与值
        conflict_columns : List[str]
            冲突检测的列（主键或唯一约束）
        """
        columns = list(data.keys())
        values = list(data.values())
        placeholders = ", ".join(["?"] * len(columns))
        col_str = ", ".join(columns)

        update_clause = ", ".join([f"{col}=excluded.{col}" for col in columns if col not in conflict_columns])
        conflict_str = ", ".join(conflict_columns)

        sql = f"""
            INSERT INTO {table} ({col_str}) VALUES ({placeholders})
            ON CONFLICT({conflict_str}) DO UPDATE SET {update_clause}
        """
        self.conn.execute(sql, values)
        self.commit()

    # -------------------------------
    # 数据查询
    # -------------------------------
    def query(self, sql: str, params: Optional[Tuple] = None) -> pd.DataFrame:
        """
        执行查询并返回 DataFrame

        Parameters
        ----------
        sql : str
            SQL 查询语句
        params : Tuple, optional
            参数化查询参数

        Returns
        -------
        pd.DataFrame
        """
        if params:
            return pd.read_sql(sql, self.conn, params=params)
        else:
            return pd.read_sql(sql, self.conn)

    def select(self, table: str, columns: List[str] = None, where: str = None,
               params: Tuple = None, order_by: str = None) -> pd.DataFrame:
        """
        简化的 SELECT 查询

        Parameters
        ----------
        table : str
            表名
        columns : List[str], optional
            要查询的列，默认 *
        where : str, optional
            WHERE 子句（不含 WHERE 关键字）
        params : Tuple, optional
            参数化查询参数
        order_by : str, optional
            ORDER BY 子句

        Returns
        -------
        pd.DataFrame
        """
        col_str = ", ".join(columns) if columns else "*"
        sql = f"SELECT {col_str} FROM {table}"
        if where:
            sql += f" WHERE {where}"
        if order_by:
            sql += f" ORDER BY {order_by}"
        return self.query(sql, params)

    # -------------------------------
    # 业务专用方法
    # -------------------------------
    def get_stock_info(self, fields: List[str] = None) -> pd.DataFrame:
        """
        获取股票基本信息（兼容原有接口）

        Parameters
        ----------
        fields : List[str], optional
            要返回的字段列表，默认全部

        Returns
        -------
        pd.DataFrame
        """
        if fields is None:
            query = "SELECT * FROM stock_basic"
        else:
            field_str = ", ".join(fields)
            query = f"SELECT {field_str} FROM stock_basic"

        df = pd.read_sql(query, self.conn)

        # 防御性处理
        if "industry" in df.columns:
            df["industry"] = df["industry"].fillna("UNKNOWN")

        return df

    def get_last_update_date(self, ts_code: str) -> Optional[str]:
        """获取某只股票在 data_meta 表中的最新更新日期"""
        df = self.select("data_meta", ["last_update_date"], where="ts_code = ?", params=(ts_code,))
        if df.empty:
            return None
        return df.iloc[0]["last_update_date"]