"""
因子计算引擎（扩展版）
封装常用的技术指标和因子，支持多股票面板数据（DataFrame）
新增斜率、最大量比等因子，适配慢牛低换手策略
"""

import pandas as pd
import numpy as np


class FactorEngine:
    """因子计算引擎，所有方法返回添加新列后的 DataFrame"""

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
        """N 日年化波动率（收益率标准差 * sqrt(252)）"""
        df = df.copy()
        ret = df.groupby("ts_code")["close"].pct_change()
        vol = ret.groupby(df["ts_code"]).rolling(period).std().reset_index(level=0, drop=True)
        df[f"volatility_{period}"] = vol * np.sqrt(252)
        return df

    @staticmethod
    def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """平均真实波幅 (ATR)，需要 high, low, close 列"""
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

    @staticmethod
    def add_atr_2x_pct(df: pd.DataFrame) -> pd.DataFrame:
        """2倍ATR占收盘价的百分比（用于突破阈值比较）"""
        df = df.copy()
        if "atr_14" not in df.columns:
            raise KeyError("需要先计算 atr_14 才能使用 atr_2x_pct")
        df["atr_2x_pct"] = 2 * df["atr_14"] / df["close"] * 100
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

    # ---------- 估值相关因子 ----------
    @staticmethod
    def add_pe_percentile(df: pd.DataFrame, period: int = 252) -> pd.DataFrame:
        """PE(TTM) 在 N 日内的分位数（需已加载 pe_ttm）"""
        df = df.copy()
        if "pe_ttm" not in df.columns:
            raise KeyError("缺少 pe_ttm 列，请确保加载数据时包含 daily_basic")
        df[f"pe_rank_{period}"] = (
            df.groupby("ts_code")["pe_ttm"]
            .rolling(period, min_periods=period // 2)
            .apply(lambda x: (x.iloc[-1] > x).mean(), raw=False)
            .reset_index(level=0, drop=True)
        )
        return df

    # ---------- 新增：趋势与量能稳定性因子 ----------
    @staticmethod
    def add_slope(df: pd.DataFrame, period: int = 120) -> pd.DataFrame:
        """
        计算每只股票收盘价的线性回归斜率（滚动窗口）
        斜率 = (N * Σ(xy) - Σx * Σy) / (N * Σ(x²) - (Σx)²)
        x = 0,1,...,N-1
        """
        df = df.copy().sort_values(["ts_code", "trade_date"])
        x = np.arange(period)
        x_mean = x.mean()
        sum_x = x.sum()
        sum_x_sq = (x ** 2).sum()

        def _calc_slope(series):
            if len(series) < period:
                return np.nan
            y = series.values[-period:]
            sum_y = y.sum()
            sum_xy = (x * y).sum()
            slope = (period * sum_xy - sum_x * sum_y) / (period * sum_x_sq - sum_x ** 2)
            return slope

        df[f"slope_{period}"] = (
            df.groupby("ts_code")["close"]
            .rolling(period, min_periods=period)
            .apply(_calc_slope, raw=False)
            .reset_index(level=0, drop=True)
        )
        return df

    @staticmethod
    def add_volume_ratio_max(df: pd.DataFrame, period: int = 120) -> pd.DataFrame:
        """
        计算滚动窗口内单日量比的最大值（用于过滤异常放量）
        量比 = 当日成交量 / 过去 period 日均量（不含当日）
        """
        df = df.copy().sort_values(["ts_code", "trade_date"])
        # 计算不含当日的 period 日均量
        df["vol_ma_ex"] = (
            df.groupby("ts_code")["vol"]
            .shift(1)
            .rolling(period, min_periods=period)
            .mean()
            .reset_index(level=0, drop=True)
        )
        df["vol_ratio_daily"] = df["vol"] / df["vol_ma_ex"]
        df[f"volume_ratio_max{period}"] = (
            df.groupby("ts_code")["vol_ratio_daily"]
            .rolling(period, min_periods=period)
            .max()
            .reset_index(level=0, drop=True)
        )
        # 清理临时列
        df.drop(["vol_ma_ex", "vol_ratio_daily"], axis=1, inplace=True)
        return df

    # ---------- 批量计算入口 ----------
    @classmethod
    def compute_factors(cls, df: pd.DataFrame, factor_list: list) -> pd.DataFrame:
        """
        根据因子名称列表批量计算因子

        Parameters
        ----------
        df : pd.DataFrame
            原始数据（需包含 ts_code, trade_date, 以及对应因子所需的列）
        factor_list : list
            因子名称列表，支持灵活命名。新增斜率和最大量比因子名示例：
            - 'slope_120' : 120日收盘价斜率
            - 'volume_ratio_max120' : 120日内最大量比

        Returns
        -------
        pd.DataFrame
            添加了因子的 DataFrame
        """
        result = df.copy()
        for factor in factor_list:
            parts = factor.split("_")
            
            # ---- 收益率类 ----
            if parts[0] in ("ret", "return") and len(parts) == 2 and parts[1].isdigit():
                result = cls.add_return(result, int(parts[1]))
            elif parts[0] == "logret" and len(parts) == 2 and parts[1].isdigit():
                result = cls.add_log_return(result, int(parts[1]))
            
            # ---- 均线类 ----
            elif parts[0] == "ma" and len(parts) == 2 and parts[1].isdigit():
                result = cls.add_ma(result, int(parts[1]))
            elif parts[0] == "ema" and len(parts) == 2 and parts[1].isdigit():
                result = cls.add_ema(result, int(parts[1]))
            elif parts[0] == "bias" and len(parts) == 2 and parts[1].isdigit():
                result = cls.add_ma_deviation(result, int(parts[1]))
            
            # ---- 波动率类 ----
            elif parts[0] == "volatility" and len(parts) == 2 and parts[1].isdigit():
                result = cls.add_volatility(result, int(parts[1]))
            elif parts[0] == "atr" and len(parts) >= 2 and parts[1].isdigit():
                result = cls.add_atr(result, int(parts[1]))
            elif factor == "atr_2x_pct":
                result = cls.add_atr_2x_pct(result)
            
            # ---- 成交量类 ----
            elif parts[0] == "vol" and len(parts) >= 2:
                if parts[1] == "ma" and len(parts) == 3 and parts[2].isdigit():
                    result = cls.add_volume_ma(result, int(parts[2]))
                elif parts[1] == "ratio" and len(parts) == 3 and parts[2].isdigit():
                    result = cls.add_volume_ratio(result, int(parts[2]))
                else:
                    print(f"警告: 未知成交量因子 '{factor}'，已跳过")
            
            # ---- 新增：斜率因子 (slope_120) ----
            elif parts[0] == "slope" and len(parts) == 2 and parts[1].isdigit():
                result = cls.add_slope(result, int(parts[1]))
            
            # ---- 新增：最大量比因子 (volume_ratio_max120) ----
            elif factor.startswith("volume_ratio_max") and factor[len("volume_ratio_max"):].isdigit():
                period = int(factor[len("volume_ratio_max"):])
                result = cls.add_volume_ratio_max(result, period)
            
            # ---- 其他已有因子 ----
            elif factor == "obv":
                result = cls.add_obv(result)
            elif parts[0] == "consecutive" and parts[1] == "up" and len(parts) == 3 and parts[2].isdigit():
                result = cls.add_consecutive_up_days(result, int(parts[2]))
            elif parts[0] == "rsi" and len(parts) == 2 and parts[1].isdigit():
                result = cls.add_rsi(result, int(parts[1]))
            elif factor == "macd":
                result = cls.add_macd(result)
            elif parts[0] == "perank" and len(parts) == 2 and parts[1].isdigit():
                result = cls.add_pe_percentile(result, int(parts[1]))
            else:
                print(f"警告: 未知因子 '{factor}'，已跳过")
        return result