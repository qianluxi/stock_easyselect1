"""
混合数据加载器（历史 SQLite + 当日 efinance）
支持盘中多日窗口策略，完全兼容现有策略引擎
"""
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Optional, List
from datetime import datetime

try:
    import efinance as ef
except ImportError:
    raise ImportError("请先安装 efinance：pip install efinance")

from core.data_loader import DataLoader


class EfinanceLiveLoader:
    """
    混合加载器
    - 历史数据：从本地 stock.db 读取，含 daily_basic 字段
    - 当日数据：从 efinance 实时行情获取
    """

    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_loader = DataLoader(str(self.db_path))

    @staticmethod
    def _format_ts_code(code: str) -> str:
        """将 efinance 的数字代码转换为带后缀的 Tushare 格式"""
        if "." in code:
            return code
        if code.startswith(("6", "9")):
            return f"{code}.SH"
        return f"{code}.SZ"

    def load_daily(
        self,
        trade_date: Optional[str] = None,
        ts_codes: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """获取当日实时行情，返回与数据库字段一致的 DataFrame"""
        df = ef.stock.get_realtime_quotes()
        if df.empty:
            raise RuntimeError("实时行情数据为空，请确认是否在交易时段")

        column_mapping = {
            "股票代码": "ts_code_raw",
            "最新价": "close",
            "涨跌幅": "pct_chg",
            "成交量": "vol",
            "成交额": "amount",
            "换手率": "turnover",
            "量比": "volume_ratio",
            "最高": "high",
            "最低": "low",
            "今开": "open",
            "昨日收盘": "pre_close",
            "总市值": "total_mv_raw",
            "流通市值": "circ_mv_raw",
            "动态市盈率": "pe_ttm",
        }
        df = df.rename(columns=column_mapping)
        df["ts_code"] = df["ts_code_raw"].apply(self._format_ts_code)

        # 清洗数值列
        numeric_cols = [
            "close", "pct_chg", "vol", "amount", "turnover",
            "volume_ratio", "open", "high", "low", "pre_close",
            "total_mv_raw", "circ_mv_raw", "pe_ttm"
        ]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = df[col].astype(str).str.replace("%", "", regex=False)
                df[col] = df[col].str.replace(",", "", regex=False)
                df[col] = df[col].replace("-", pd.NA)
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # 单位换算
        df["amount"] = df["amount"] / 1000               # 元 → 千元
        df["total_mv"] = df["total_mv_raw"] / 10000      # 元 → 万元
        df["circ_mv"] = df["circ_mv_raw"] / 10000
        df["change"] = df["close"] - df["pre_close"]

        # 保留统一字段
        keep = [
            "ts_code", "open", "high", "low", "close", "pre_close",
            "change", "pct_chg", "vol", "amount", "volume_ratio",
            "turnover", "total_mv", "circ_mv", "pe_ttm"
        ]
        for c in keep:
            if c not in df.columns:
                df[c] = None
        df = df[keep]

        if ts_codes:
            df = df[df["ts_code"].isin(ts_codes)]

        return df.dropna(subset=["close", "pct_chg"])

    def load_window(
        self,
        start_date: str,
        end_date: str,
        ts_codes: Optional[List[str]] = None,
        include_basic: bool = True,
    ) -> pd.DataFrame:
        """
        返回 start_date ~ end_date 的面板数据
        历史部分从本地数据库读取（含 daily_basic），当日用实时数据补齐
        """
        end_dt = pd.to_datetime(end_date)
        prev_date = (end_dt - pd.Timedelta(days=1)).strftime("%Y-%m-%d")

        # 1. 加载历史数据（含 daily_basic）
        hist = self.db_loader.load_window(start_date, prev_date, ts_codes, include_basic=True)
        hist = hist[hist["trade_date"] != end_date]  # 避免重复

        # 2. 加载当日实时数据
        today = self.load_daily(trade_date=end_date, ts_codes=ts_codes)
        today["trade_date"] = end_date

        # 3. 对齐所有列，消除 FutureWarning
        all_cols = list(set(hist.columns).union(set(today.columns)))
        for col in all_cols:
            if col not in hist.columns:
                hist[col] = np.nan
            if col not in today.columns:
                today[col] = np.nan

        # 4. 合并并排序
        df = pd.concat([hist, today], ignore_index=True, sort=False)
        df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

        # 5. 确保 turnover 列存在（部分策略直接用 turnover）
        if "turnover" not in df.columns and "turnover_rate" in df.columns:
            df["turnover"] = df["turnover_rate"]
        elif "turnover" not in df.columns and "turnover_rate_f" in df.columns:
            df["turnover"] = df["turnover_rate_f"]

        return df

    def get_latest_trade_date(self) -> str:
        """返回当天日期作为最新交易日"""
        return datetime.today().strftime("%Y-%m-%d")