"""
因子计算引擎
封装常用的技术指标和因子，支持多股票面板数据（DataFrame）
所有方法均为静态方法，接收 DataFrame 并返回添加新列后的 DataFrame
"""

import pandas as pd
import numpy as np


class FactorEngine:
    """因子计算引擎"""

    # ---------- 收益率类因子 ----------
    @staticmethod
    def add_return(df: pd.DataFrame, period: int = 1) -> pd.DataFrame:
        """N 日收益率（基于收盘价）"""
        df = df.copy()
        df[f"ret_{period}"] = df.groupby("ts_code")["close"].pct_change(period)
        return df

    @staticmethod
    def add_log_return(df: pd.DataFrame, period: int = 1) -> pd.DataFrame:
        """N 日对数收益率"""
        df = df.copy()
        df[f"log_ret_{period}"] = np.log(df["close"] / df.groupby("ts_code")["close"].shift(period))
        return df

    # ---------- 均线类因子 ----------
    @staticmethod
    def add_ma(df: pd.DataFrame, period: int, price_col: str = "close") -> pd.DataFrame:
        """N 日简单移动平均线"""
        df = df.copy()
        df[f"ma_{period}"] = (
            df.groupby("ts_code")[price_col]
            .rolling(period, min_periods=1)
            .mean()
            .reset_index(level=0, drop=True)
        )
        return df

    @staticmethod
    def add_ema(df: pd.DataFrame, period: int, price_col: str = "close") -> pd.DataFrame:
        """N 日指数移动平均线"""
        df = df.copy()
        df[f"ema_{period}"] = (
            df.groupby("ts_code")[price_col]
            .ewm(span=period, adjust=False)
            .mean()
            .reset_index(level=0, drop=True)
        )
        return df

    @staticmethod
    def add_ma_deviation(df: pd.DataFrame, period: int, price_col: str = "close") -> pd.DataFrame:
        """价格与 N 日均线的偏离度（乖离率）"""
        df = FactorEngine.add_ma(df, period, price_col)
        df[f"bias_{period}"] = (df[price_col] - df[f"ma_{period}"]) / df[f"ma_{period}"]
        return df

    # ---------- 波动率类因子 ----------
    @staticmethod
    def add_volatility(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
        """N 日波动率（收益率标准差年化）"""
        df = df.copy()
        ret = df.groupby("ts_code")["close"].pct_change()
        vol = ret.groupby(df["ts_code"]).rolling(period).std().reset_index(level=0, drop=True)
        df[f"volatility_{period}"] = vol * np.sqrt(252)
        return df

    @staticmethod
    def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """
        平均真实波幅 (ATR)
        需要 high, low, close 列
        """
        df = df.copy().sort_values(["ts_code", "trade_date"])
        df["prev_close"] = df.groupby("ts_code")["close"].shift(1)
        df["tr"] = np.maximum(
            df["high"] - df["low"],
            np.maximum(
                abs(df["high"] - df["prev_close"]),
                abs(df["low"] - df["prev_close"])
            )
        )
        df[f"atr_{period}"] = (
            df.groupby("ts_code")["tr"]
            .rolling(period, min_periods=1)
            .mean()
            .reset_index(level=0, drop=True)
        )
        df.drop(["prev_close", "tr"], axis=1, inplace=True)
        return df

    # ---------- 成交量/量比类因子 ----------
    @staticmethod
    def add_volume_ma(df: pd.DataFrame, period: int) -> pd.DataFrame:
        """成交量 N 日均值"""
        df = df.copy()
        df[f"vol_ma_{period}"] = (
            df.groupby("ts_code")["vol"]
            .rolling(period, min_periods=1)
            .mean()
            .reset_index(level=0, drop=True)
        )
        return df

    @staticmethod
    def add_volume_ratio(df: pd.DataFrame, period: int) -> pd.DataFrame:
        """N 日量比 = 当日成交量 / N 日均量"""
        df = FactorEngine.add_volume_ma(df, period)
        df[f"vol_ratio_{period}"] = df["vol"] / df[f"vol_ma_{period}"]
        return df

    @staticmethod
    def add_obv(df: pd.DataFrame) -> pd.DataFrame:
        """能量潮 (OBV)"""
        df = df.copy().sort_values(["ts_code", "trade_date"])
        df["direction"] = np.where(df["close"] > df["pre_close"], 1,
                                   np.where(df["close"] < df["pre_close"], -1, 0))
        df["obv"] = (df["direction"] * df["vol"]).groupby(df["ts_code"]).cumsum()
        df.drop("direction", axis=1, inplace=True)
        return df

    # ---------- 价格形态类因子 ----------
    @staticmethod
    def add_consecutive_up_days(df: pd.DataFrame, n: int) -> pd.DataFrame:
        """是否连续 N 日上涨（当日涨幅 > 0）"""
        df = df.copy()
        df["is_up"] = df["pct_chg"] > 0
        df[f"consecutive_up_{n}"] = (
            df.groupby("ts_code")["is_up"]
            .rolling(n, min_periods=n)
            .apply(lambda x: x.all(), raw=True)
            .reset_index(level=0, drop=True)
        )
        df.drop("is_up", axis=1, inplace=True)
        return df

    @staticmethod
    def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """相对强弱指数 RSI"""
        df = df.copy().sort_values(["ts_code", "trade_date"])
        delta = df.groupby("ts_code")["close"].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.groupby(df["ts_code"]).rolling(period, min_periods=1).mean().reset_index(level=0, drop=True)
        avg_loss = loss.groupby(df["ts_code"]).rolling(period, min_periods=1).mean().reset_index(level=0, drop=True)
        rs = avg_gain / avg_loss
        df[f"rsi_{period}"] = 100 - (100 / (1 + rs))
        return df

    @staticmethod
    def add_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
        """MACD 指标（返回 DIF, DEA, MACD 柱）"""
        df = df.copy().sort_values(["ts_code", "trade_date"])
        df["ema_fast"] = df.groupby("ts_code")["close"].ewm(span=fast, adjust=False).mean().reset_index(level=0, drop=True)
        df["ema_slow"] = df.groupby("ts_code")["close"].ewm(span=slow, adjust=False).mean().reset_index(level=0, drop=True)
        df["dif"] = df["ema_fast"] - df["ema_slow"]
        df["dea"] = df.groupby("ts_code")["dif"].ewm(span=signal, adjust=False).mean().reset_index(level=0, drop=True)
        df["macd"] = 2 * (df["dif"] - df["dea"])
        df.drop(["ema_fast", "ema_slow"], axis=1, inplace=True)
        return df

    # ---------- 估值相关因子（需要 daily_basic 数据） ----------
    @staticmethod
    def add_pe_percentile(df: pd.DataFrame, period: int = 252) -> pd.DataFrame:
        """PE(TTM) 在 N 日内的分位数（需已加载 pe_ttm）"""
        df = df.copy()
        if "pe_ttm" not in df.columns:
            raise KeyError("缺少 pe_ttm 列，请确保加载数据时包含 daily_basic")
        df[f"pe_rank_{period}"] = (
            df.groupby("ts_code")["pe_ttm"]
            .rolling(period, min_periods=period//2)
            .apply(lambda x: (x.iloc[-1] > x).mean(), raw=False)
            .reset_index(level=0, drop=True)
        )
        return df

    # ---------- 批量计算入口 ----------
    @classmethod
    def compute_factors(cls, df: pd.DataFrame, factor_list: list) -> pd.DataFrame:
        """
        根据因子名称列表批量计算因子

        Parameters
        ----------
        df : pd.DataFrame
            原始数据
        factor_list : list
            因子名称列表，支持灵活命名，例如：
            - 'ret_5' 或 'return_5'
            - 'ma_5', 'ema_5'
            - 'bias_5'
            - 'volatility_20'
            - 'atr_14'
            - 'vol_ma_5', 'vol_ratio_5'
            - 'obv'
            - 'consecutive_up_3'
            - 'rsi_14'
            - 'macd'
            - 'pe_rank_252'

        Returns
        -------
        pd.DataFrame
            添加了因子的 DataFrame
        """
        result = df.copy()
        for factor in factor_list:
            parts = factor.split("_")
            
            # 收益率类 (ret_5, return_5)
            if parts[0] in ("ret", "return") and len(parts) == 2 and parts[1].isdigit():
                result = cls.add_return(result, int(parts[1]))
            elif parts[0] == "logret" and len(parts) == 2 and parts[1].isdigit():
                result = cls.add_log_return(result, int(parts[1]))
            
            # 均线类 (ma_5, ema_5)
            elif parts[0] == "ma" and len(parts) == 2 and parts[1].isdigit():
                result = cls.add_ma(result, int(parts[1]))
            elif parts[0] == "ema" and len(parts) == 2 and parts[1].isdigit():
                result = cls.add_ema(result, int(parts[1]))
            elif parts[0] == "bias" and len(parts) == 2 and parts[1].isdigit():
                result = cls.add_ma_deviation(result, int(parts[1]))
            
            # 波动率类
            elif parts[0] == "volatility" and len(parts) == 2 and parts[1].isdigit():
                result = cls.add_volatility(result, int(parts[1]))
            elif parts[0] == "atr" and len(parts) == 2 and parts[1].isdigit():
                result = cls.add_atr(result, int(parts[1]))
            
            # 成交量类 (vol_ma_5, vol_ratio_5)
            elif parts[0] == "vol" and len(parts) >= 2:
                if parts[1] == "ma" and len(parts) == 3 and parts[2].isdigit():
                    result = cls.add_volume_ma(result, int(parts[2]))
                elif parts[1] == "ratio" and len(parts) == 3 and parts[2].isdigit():
                    result = cls.add_volume_ratio(result, int(parts[2]))
                else:
                    print(f"警告: 未知成交量因子 '{factor}'，已跳过")
            
            # OBV
            elif factor == "obv":
                result = cls.add_obv(result)
            
            # 连续上涨 (consecutive_up_3)
            elif parts[0] == "consecutive" and parts[1] == "up" and len(parts) == 3 and parts[2].isdigit():
                result = cls.add_consecutive_up_days(result, int(parts[2]))
            
            # RSI
            elif parts[0] == "rsi" and len(parts) == 2 and parts[1].isdigit():
                result = cls.add_rsi(result, int(parts[1]))
            
            # MACD
            elif factor == "macd":
                result = cls.add_macd(result)
            
            # PE 分位数
            elif parts[0] == "perank" and len(parts) == 2 and parts[1].isdigit():
                result = cls.add_pe_percentile(result, int(parts[1]))
            
            else:
                print(f"警告: 未知因子 '{factor}'，已跳过")
        return result