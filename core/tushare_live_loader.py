"""
Tushare 实时行情数据加载器（积分 ≥ 120）
基于 pro.realtime_list() 接口，用于盘中 14:30 筛选
"""

import pandas as pd
from typing import Optional, List


class TushareLiveLoader:
    """Tushare 实时行情加载器"""

    def __init__(self, pro):
        """
        Parameters
        ----------
        pro : tushare.pro_api 实例
            已初始化并拥有 120+ 积分的 pro 对象
        """
        self.pro = pro

    def load_daily(self, trade_date=None, ts_codes=None):
        # 获取沪深实时行情
        df_ss = self.pro.realtime_quote(src='sse')
        df_sz = self.pro.realtime_quote(src='sz')
        df = pd.concat([df_ss, df_sz], ignore_index=True)

        if df.empty:
            raise RuntimeError("实时行情数据为空，请检查交易时间或权限")

        # 字段映射
        column_mapping = {
            "ts_code": "ts_code",
            "price": "close",
            "pct_chg": "pct_chg",
            "vol": "vol",
            "amount": "amount",
            "turnover_rate": "turnover",
            "volume_ratio": "volume_ratio",
        }
        df = df.rename(columns=column_mapping)

        # 只保留必要列
        needed_cols = ["ts_code", "close", "pct_chg", "vol", "amount", "turnover", "volume_ratio"]
        for col in needed_cols:
            if col not in df.columns:
                df[col] = None
        df = df[needed_cols].copy()

        # 类型转换
        for col in ["pct_chg", "vol", "amount", "turnover", "volume_ratio"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # 成交额单位：元 → 千元
        df["amount"] = df["amount"] / 1000

        df = df.dropna(subset=["close", "pct_chg"])

        if ts_codes:
            df = df[df["ts_code"].isin(ts_codes)]

        return df

    def load_window(
        self,
        start_date: str,
        end_date: str,
        ts_codes: Optional[List[str]] = None,
        include_basic: bool = True,
    ) -> pd.DataFrame:
        """盘中模式不支持多日历史，降级为单日"""
        print("[Live] 实时模式不支持历史窗口，仅返回实时快照")
        return self.load_daily(None, ts_codes)
    
    def get_latest_trade_date(self) -> str:
        """返回当前日期作为最新交易日期（盘中实时模式）"""
        from datetime import datetime
        return datetime.today().strftime("%Y-%m-%d")