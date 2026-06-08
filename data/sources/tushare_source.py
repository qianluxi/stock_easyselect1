"""
Tushare 数据源实现 (批量优化版)
封装 Tushare Pro 接口，支持按日期批量拉取多只股票和 ETF 数据。
新增：自动分批处理，避免单次请求超过1000个代码限制。
"""

import time
import random
from typing import List, Optional
import pandas as pd
import tushare as ts
from utils.network import disable_proxy

# 禁用系统代理，防止网络问题
disable_proxy()

# 请求间隔范围（秒），批量请求后调用
SLEEP_RANGE = (0.2, 0.5)

# Tushare daily 接口默认字段（基础字段）
DAILY_BASE_FIELDS = "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"

# 扩展字段（需要更高积分权限，若无则自动降级）
DAILY_EXTENDED_FIELDS = "total_mv,turnover_rate"

# ETF 日线字段（无市值、换手率等个股特有字段，但保留基本价格与量能，方便复用）
ETF_DAILY_FIELDS = "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"

# 单次请求最大股票数量（Tushare 限制为1000，留有余量，现在改为100）
BATCH_SIZE = 100


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

    # ------------------------------------------------------------
    # 内部辅助：分批请求
    # ------------------------------------------------------------
    def _batch_request(self, request_func, symbols: List[str], *args, **kwargs) -> pd.DataFrame:
        """
        将 symbols 按 BATCH_SIZE 分批，依次调用 request_func 并合并结果。
        request_func 需接收 (symbols_batch, *args, **kwargs) 并返回 DataFrame。
        """
        if not symbols:
            return pd.DataFrame()
        all_results = []
        for i in range(0, len(symbols), BATCH_SIZE):
            batch = symbols[i:i + BATCH_SIZE]
            try:
                df = request_func(batch, *args, **kwargs)
                if df is not None and not df.empty:
                    all_results.append(df)
            except Exception as e:
                print(f"[Tushare] 批次请求失败: {e}")
            time.sleep(random.uniform(*SLEEP_RANGE))
        if not all_results:
            return pd.DataFrame()
        return pd.concat(all_results, ignore_index=True)

    # ------------------------------------------------------------
    # 日线行情（股票）
    # ------------------------------------------------------------
    def fetch_daily(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        **kwargs
    ) -> pd.DataFrame:
        if not symbols:
            return pd.DataFrame()

        if "fields" in kwargs:
            fields = kwargs.pop("fields")
        else:
            fields = f"{DAILY_BASE_FIELDS},{DAILY_EXTENDED_FIELDS}"

        def _request_batch(batch, fields_used):
            ts_code_str = ",".join(batch)
            return self.pro.daily(
                ts_code=ts_code_str,
                start_date=start_date,
                end_date=end_date,
                fields=fields_used
            )

        # 先尝试用包含扩展字段的请求
        try:
            df = self._batch_request(lambda b: _request_batch(b, fields), symbols)
        except Exception as e:
            # 如果请求抛出异常（例如权限不足、字段不支持），降级为基础字段
            if "total_mv" in fields or "turnover_rate" in fields:
                print(f"[Tushare] 扩展字段请求异常，降级为基础字段。 错误: {e}")
                try:
                    df = self._batch_request(lambda b: _request_batch(b, DAILY_BASE_FIELDS), symbols)
                except Exception as e2:
                    print(f"[Tushare] 基础字段请求失败: {e2}")
                    return pd.DataFrame()
            else:
                print(f"[Tushare] 日线请求失败: {e}")
                return pd.DataFrame()

        # 如果 df 为空（可能因为所有批次都无数据），直接返回
        if df is None or df.empty:
            print(f"[Tushare] 批量日线无数据: {start_date}-{end_date}")
            return pd.DataFrame()

        # 基础数据清洗
        df = self._clean_daily_data(df)
        return df

    # ------------------------------------------------------------
    # ETF 日线（逐只拉取，接口不支持批量）
    # ------------------------------------------------------------
    def fetch_etf_daily(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        **kwargs
    ) -> pd.DataFrame:
        """逐只拉取 ETF 日线数据（该接口不支持批量）"""
        if not symbols:
            return pd.DataFrame()

        if "fields" in kwargs:
            fields = kwargs.pop("fields")
        else:
            fields = ETF_DAILY_FIELDS

        all_data = []
        for symbol in symbols:
            try:
                df = self.pro.fund_daily(
                    ts_code=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    fields=fields
                )
                if df is not None and not df.empty:
                    all_data.append(df)
            except Exception as e:
                print(f"[Tushare] 获取 ETF {symbol} 失败: {e}")
            time.sleep(random.uniform(*SLEEP_RANGE))

        if not all_data:
            return pd.DataFrame()

        result = pd.concat(all_data, ignore_index=True)
        result["trade_date"] = pd.to_datetime(result["trade_date"], format="%Y%m%d")
        return result

    # ------------------------------------------------------------
    # 复权因子（支持分批）
    # ------------------------------------------------------------
    def fetch_adjust_factor(
        self,
        trade_date: Optional[str] = None,
        symbols: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """
        获取复权因子（支持按日期和/或股票筛选）
        当 symbols 不为空时，自动分批拉取。
        """
        if symbols:
            # 分批拉取
            def _adj_batch(batch):
                params = {"ts_code": ",".join(batch), "fields": "ts_code,trade_date,adj_factor"}
                if trade_date:
                    params["trade_date"] = trade_date
                return self.pro.adj_factor(**params)

            df = self._batch_request(_adj_batch, symbols)
            if df.empty:
                return df
        else:
            # 未指定 symbols，拉取全市场（一般不触发1000限制）
            params = {"fields": "ts_code,trade_date,adj_factor"}
            if trade_date:
                params["trade_date"] = trade_date
            try:
                df = self.pro.adj_factor(**params)
                if df is None:
                    return pd.DataFrame()
            except Exception as e:
                print(f"[Tushare] 获取复权因子失败: {e}")
                return pd.DataFrame()

        # 统一日期格式
        df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
        return df

    def fetch_adjust_factor_by_date(self, trade_date: str, symbols: Optional[List[str]] = None) -> pd.DataFrame:
        """
        按指定日期批量拉取复权因子（便利方法，与 fetch_adjust_factor 一致）
        """
        return self.fetch_adjust_factor(trade_date=trade_date, symbols=symbols)

    # ------------------------------------------------------------
    # 交易日历
    # ------------------------------------------------------------
    def fetch_trade_calendar(
        self,
        start_date: str,
        end_date: str,
        exchange: str = "SSE"
    ) -> pd.DataFrame:
        """
        获取交易日历
        """
        try:
            df = self.pro.trade_cal(
                exchange=exchange,
                start_date=start_date,
                end_date=end_date,
                fields="cal_date,is_open,pretrade_date"
            )
            if df is None:
                return pd.DataFrame()
            return df
        except Exception as e:
            print(f"[Tushare] 获取交易日历失败: {e}")
            return pd.DataFrame()

    # ------------------------------------------------------------
    # 每日基本面指标（逐只拉取）
    # ------------------------------------------------------------
    def fetch_daily_basic(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        fields: str = None
    ) -> pd.DataFrame:
        """批量拉取 daily_basic（改为分批，不再逐只）"""
        if not symbols:
            return pd.DataFrame()

        if fields is None:
            fields = "ts_code,trade_date,total_mv,circ_mv,turnover_rate,turnover_rate_f,volume_ratio,pe,pe_ttm,pb"

        def _request_batch(batch):
            ts_code_str = ",".join(batch)
            return self.pro.daily_basic(
                ts_code=ts_code_str,
                start_date=start_date,
                end_date=end_date,
                fields=fields
            )

        # 使用通用的分批请求方法
        df = self._batch_request(_request_batch, symbols)
        if not df.empty:
            df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
        return df

    # ========================
    # 内部辅助方法
    # ========================

    def _clean_daily_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """对 Tushare 返回的日线数据进行清洗和类型转换"""
        if df.empty:
            return df

        df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d", errors="coerce")

        numeric_cols_candidates = [
            "open", "high", "low", "close",
            "pre_close", "change", "pct_chg",
            "vol", "amount", "total_mv", "turnover_rate"
        ]
        for col in numeric_cols_candidates:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        key_cols = ["open", "high", "low", "close"]
        df = df.dropna(subset=key_cols)

        return df