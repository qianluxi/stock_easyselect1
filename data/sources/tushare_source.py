"""
Tushare 数据源实现 (批量优化版)
封装 Tushare Pro 接口，支持按日期批量拉取多只股票和 ETF 数据。
新增：自动分批处理、重试机制、批次间冷却，避免频率限制。
"""

import time
import random
from typing import List, Optional
import pandas as pd
import tushare as ts
from utils.network import disable_proxy

# 禁用系统代理，防止网络问题
disable_proxy()

# 请求间隔范围（秒），每次成功请求后随机等待
SLEEP_RANGE = (5.0, 12.0)

# 批次间强制冷却：每 COOL_DOWN_INTERVAL 个批次后，额外等待 COOL_DOWN_SECONDS 秒
COOL_DOWN_INTERVAL = 1
COOL_DOWN_SECONDS = 11

# 失败重试次数
MAX_RETRIES = 2
# 重试前等待秒数
RETRY_DELAY = 20

# Tushare daily 接口默认字段（基础字段）
DAILY_BASE_FIELDS = "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"

# 扩展字段（需要更高积分权限，若无则自动降级）
DAILY_EXTENDED_FIELDS = "total_mv,turnover_rate"

# ETF 日线字段（无市值、换手率等个股特有字段，但保留基本价格与量能，方便复用）
ETF_DAILY_FIELDS = "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"

# 单次请求最大股票数量（Tushare 限制为1000，现在设为100以降低频率风险）
BATCH_SIZE = 70


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
    # 内部辅助：分批请求（增强版：重试 + 冷却）
    # ------------------------------------------------------------
    def _batch_request(self, request_func, symbols: List[str], *args, **kwargs) -> pd.DataFrame:
        """
        将 symbols 按 BATCH_SIZE 分批，依次调用 request_func 并合并结果。
        支持失败重试和批次间强制冷却，避免触发 Tushare 频率限制。
        """
        if not symbols:
            return pd.DataFrame()

        all_results = []
        total_batches = (len(symbols) + BATCH_SIZE - 1) // BATCH_SIZE

        for batch_idx, i in enumerate(range(0, len(symbols), BATCH_SIZE)):
            batch = symbols[i:i + BATCH_SIZE]

            # 重试循环
            success = False
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    df = request_func(batch, *args, **kwargs)
                    if df is not None and not df.empty:
                        all_results.append(df)
                        success = True
                    else:
                        # 返回空数据，也算作一次尝试，但可能不需要重试
                        # 但空数据可能是暂时的，所以继续重试
                        print(f"[Tushare] 批次 {batch_idx+1}/{total_batches} 返回空数据 (尝试 {attempt}/{MAX_RETRIES})")
                    break  # 如果没有异常，无论数据是否空都跳出重试循环
                except Exception as e:
                    if attempt < MAX_RETRIES:
                        print(f"[Tushare] 批次 {batch_idx+1}/{total_batches} 请求失败 (尝试 {attempt}/{MAX_RETRIES}): {e}，{RETRY_DELAY}秒后重试...")
                        time.sleep(RETRY_DELAY)
                    else:
                        print(f"[Tushare] 批次 {batch_idx+1}/{total_batches} 请求失败，已达最大重试次数: {e}")

            # 批次间请求间隔（成功或失败都等待，避免突发请求）
            time.sleep(random.uniform(*SLEEP_RANGE))

            # 每 COOL_DOWN_INTERVAL 个批次强制休息
            if (batch_idx + 1) % COOL_DOWN_INTERVAL == 0 and batch_idx + 1 < total_batches:
                print(f"[Tushare] 已处理 {batch_idx+1}/{total_batches} 批次，强制冷却 {COOL_DOWN_SECONDS} 秒...")
                time.sleep(COOL_DOWN_SECONDS)

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

        if df is None or df.empty:
            print(f"[Tushare] 批量日线无数据: {start_date}-{end_date}")
            return pd.DataFrame()

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
            # 对每只 ETF 也可应用重试（简单实现，不单独拆方法）
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    df = self.pro.fund_daily(
                        ts_code=symbol,
                        start_date=start_date,
                        end_date=end_date,
                        fields=fields
                    )
                    if df is not None and not df.empty:
                        all_data.append(df)
                    break
                except Exception as e:
                    if attempt < MAX_RETRIES:
                        print(f"[Tushare] ETF {symbol} 请求失败 (尝试 {attempt}/{MAX_RETRIES})，重试...")
                        time.sleep(RETRY_DELAY)
                    else:
                        print(f"[Tushare] 获取 ETF {symbol} 失败: {e}")
            time.sleep(random.uniform(*SLEEP_RANGE))

        if not all_data:
            return pd.DataFrame()

        result = pd.concat(all_data, ignore_index=True)
        result["trade_date"] = pd.to_datetime(result["trade_date"], format="%Y%m%d")
        return result

    def fetch_etf_daily_by_date(
        self,
        trade_date: str,
        symbols: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """
        按交易日获取全市场 ETF/基金日线（fund_daily 支持 trade_date 参数），
        再按股票池过滤。相比逐只拉取，可大幅降低请求次数。
        若接口不支持按日（权限不足等），返回空 DataFrame，由调用方回退。
        """
        try:
            df = self.pro.fund_daily(trade_date=trade_date, fields=ETF_DAILY_FIELDS)
        except Exception as e:
            print(f"[Tushare] fund_daily 按日请求失败: {e}，请改用逐只拉取模式")
            return pd.DataFrame()

        if df is None or df.empty:
            return pd.DataFrame()

        if symbols:
            df = df[df["ts_code"].isin(symbols)]

        df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
        numeric_cols = ["open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["open", "high", "low", "close"])
        return df

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
            def _adj_batch(batch):
                params = {"ts_code": ",".join(batch), "fields": "ts_code,trade_date,adj_factor"}
                if trade_date:
                    params["trade_date"] = trade_date
                return self.pro.adj_factor(**params)

            df = self._batch_request(_adj_batch, symbols)
            if df.empty:
                return df
        else:
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

        df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
        return df

    def fetch_adjust_factor_by_date(self, trade_date: str, symbols: Optional[List[str]] = None) -> pd.DataFrame:
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
    # 每日基本面指标（改为分批）
    # ------------------------------------------------------------
    def fetch_daily_basic(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        fields: str = None
    ) -> pd.DataFrame:
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
    
    def fetch_daily_by_date(self, trade_date: str, symbols: Optional[List[str]] = None) -> pd.DataFrame:
        """
        按交易日获取全市场日线数据（推荐方式，避免记录截断）
        Parameters
        ----------
        trade_date : str, format YYYYMMDD
        symbols : List[str], optional, 需要保留的股票列表
        """
        df = self.pro.daily(trade_date=trade_date, fields=DAILY_BASE_FIELDS)
        if df is None or df.empty:
            return pd.DataFrame()
        if symbols:
            df = df[df['ts_code'].isin(symbols)]
        return self._clean_daily_data(df)

    def fetch_daily_basic_by_date(self, trade_date: str, symbols: Optional[List[str]] = None) -> pd.DataFrame:
        """按交易日获取全市场 daily_basic，避免截断"""
        df = self.pro.daily_basic(trade_date=trade_date,
                                fields="ts_code,trade_date,total_mv,circ_mv,turnover_rate,turnover_rate_f,volume_ratio,pe,pe_ttm,pb")
        if df is None or df.empty:
            return pd.DataFrame()
        if symbols:
            df = df[df['ts_code'].isin(symbols)]
        df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
        return df

    def fetch_adjust_factor_by_date(self, trade_date: str, symbols: Optional[List[str]] = None) -> pd.DataFrame:
        """按交易日获取全市场复权因子，避免截断"""
        df = self.pro.adj_factor(trade_date=trade_date, fields="ts_code,trade_date,adj_factor")
        if df is None or df.empty:
            return pd.DataFrame()
        if symbols:
            df = df[df['ts_code'].isin(symbols)]
        df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
        return df
