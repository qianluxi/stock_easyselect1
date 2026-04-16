"""
Tushare 数据源实现
封装 Tushare Pro 接口，提供日线、复权因子、交易日历数据
"""

import time
import random
from typing import List, Optional
import pandas as pd
import tushare as ts
from utils.network import disable_proxy

# 禁用系统代理，防止网络问题
disable_proxy()

# 请求间隔范围（秒）
SLEEP_RANGE = (0.2, 0.5)

# Tushare daily 接口默认字段（基础字段）
DAILY_BASE_FIELDS = "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"

# 扩展字段（需要更高积分权限，若无则自动忽略）
DAILY_EXTENDED_FIELDS = "total_mv,turnover_rate"


class TushareSource:
    """Tushare Pro 数据源"""

    def __init__(self, token: str):
        """
        初始化 Tushare 数据源

        Parameters
        ----------
        token : str
            Tushare Pro API token
        """
        self.token = token
        ts.set_token(token)
        self.pro = ts.pro_api()

    def fetch_daily(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        **kwargs
    ) -> pd.DataFrame:
        """
        获取日线行情数据（包含总市值和换手率，若权限允许）

        Parameters
        ----------
        symbols : List[str]
            股票代码列表，如 ['000001.SZ', '600000.SH']
        start_date : str
            开始日期，格式 YYYYMMDD
        end_date : str
            结束日期，格式 YYYYMMDD
        **kwargs
            可选参数：
            - fields : str, 自定义返回字段，若不传则使用默认组合字段

        Returns
        -------
        pd.DataFrame
            包含字段（取决于实际返回）：
            - ts_code : 股票代码
            - trade_date : 交易日期
            - open, high, low, close : 开高低收
            - pre_close, change, pct_chg : 前收/涨跌额/涨跌幅
            - vol : 成交量（手）
            - amount : 成交额（千元）
            - total_mv : 总市值（万元，需权限）
            - turnover_rate : 换手率（%，需权限）
        """
        all_data = []

        # 构建请求字段：优先使用用户指定的 fields，否则使用默认组合
        if "fields" in kwargs:
            fields = kwargs.pop("fields")
        else:
            fields = f"{DAILY_BASE_FIELDS},{DAILY_EXTENDED_FIELDS}"

        for symbol in symbols:
            try:
                # 调用 Tushare daily 接口
                df = self.pro.daily(
                    ts_code=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    fields=fields
                )
                if df is not None and not df.empty:
                    all_data.append(df)
                else:
                    print(f"[Tushare] {symbol} 在 {start_date}-{end_date} 无数据")

            except Exception as e:
                # 若因字段权限不足导致报错，尝试降级为仅基础字段重试一次
                if "total_mv" in fields or "turnover_rate" in fields:
                    print(f"[Tushare] 获取扩展字段失败，尝试仅获取基础字段... 错误: {e}")
                    try:
                        df = self.pro.daily(
                            ts_code=symbol,
                            start_date=start_date,
                            end_date=end_date,
                            fields=DAILY_BASE_FIELDS
                        )
                        if df is not None and not df.empty:
                            all_data.append(df)
                        else:
                            print(f"[Tushare] {symbol} 基础字段也无数据")
                    except Exception as e2:
                        print(f"[Tushare] 获取 {symbol} 基础字段也失败: {e2}")
                else:
                    print(f"[Tushare] 获取 {symbol} 数据失败: {e}")

            # 控制请求频率
            time.sleep(random.uniform(*SLEEP_RANGE))

        if not all_data:
            return pd.DataFrame()

        result = pd.concat(all_data, ignore_index=True)

        # 基础数据清洗
        result = self._clean_daily_data(result)

        return result

    def fetch_adjust_factor(
        self,
        trade_date: Optional[str] = None,
        symbols: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """
        获取复权因子

        Parameters
        ----------
        trade_date : str, optional
            指定交易日期，格式 YYYYMMDD
        symbols : List[str], optional
            股票代码列表

        Returns
        -------
        pd.DataFrame
            包含字段：ts_code, trade_date, adj_factor
        """
        params = {}
        if trade_date:
            params["trade_date"] = trade_date
        if symbols:
            params["ts_code"] = ",".join(symbols)

        try:
            df = self.pro.adj_factor(**params, fields="ts_code,trade_date,adj_factor")
            return df
        except Exception as e:
            print(f"[Tushare] 获取复权因子失败: {e}")
            return pd.DataFrame()

    def fetch_trade_calendar(
        self,
        start_date: str,
        end_date: str,
        exchange: str = "SSE"
    ) -> pd.DataFrame:
        """
        获取交易日历

        Parameters
        ----------
        start_date : str
            开始日期，格式 YYYYMMDD
        end_date : str
            结束日期，格式 YYYYMMDD
        exchange : str
            交易所，可选 SSE（上交所）、SZSE（深交所）、BSE（北交所）

        Returns
        -------
        pd.DataFrame
            包含字段：cal_date, is_open, pretrade_date
        """
        try:
            df = self.pro.trade_cal(
                exchange=exchange,
                start_date=start_date,
                end_date=end_date,
                fields="cal_date,is_open,pretrade_date"
            )
            return df
        except Exception as e:
            print(f"[Tushare] 获取交易日历失败: {e}")
            return pd.DataFrame()

    # ========================
    # 内部辅助方法
    # ========================

    def _clean_daily_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """对 Tushare 返回的日线数据进行清洗和类型转换"""
        if df.empty:
            return df

        # 统一日期格式
        df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d", errors="coerce")

        # 数值列类型转换（仅转换实际存在的列）
        numeric_cols_candidates = [
            "open", "high", "low", "close",
            "pre_close", "change", "pct_chg",
            "vol", "amount", "total_mv", "turnover_rate"
        ]
        for col in numeric_cols_candidates:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # 剔除关键字段为空的记录
        key_cols = ["open", "high", "low", "close"]
        df = df.dropna(subset=key_cols)

        return df

    #获取每日基本面指标（市值、换手率、PE、PB等）
    def fetch_daily_basic(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        fields: str = None
    ) -> pd.DataFrame:
        """
        获取每日基本面指标（市值、换手率、PE、PB等）

        Parameters
        ----------
        symbols : List[str]
            股票代码列表
        start_date : str
            开始日期 YYYYMMDD
        end_date : str
            结束日期 YYYYMMDD
        fields : str, optional
            自定义返回字段，默认包含常用字段

        Returns
        -------
        pd.DataFrame
        """
        if fields is None:
            fields = "ts_code,trade_date,total_mv,circ_mv,turnover_rate,turnover_rate_f,volume_ratio,pe,pe_ttm,pb"

        all_data = []
        for symbol in symbols:
            try:
                df = self.pro.daily_basic(
                    ts_code=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    fields=fields
                )
                if df is not None and not df.empty:
                    all_data.append(df)
            except Exception as e:
                print(f"[Tushare] 获取 {symbol} daily_basic 失败: {e}")
            time.sleep(random.uniform(*SLEEP_RANGE))

        if not all_data:
            return pd.DataFrame()

        result = pd.concat(all_data, ignore_index=True)
        result["trade_date"] = pd.to_datetime(result["trade_date"], format="%Y%m%d")
        return result