"""
数据拉取调度器（优化版：按交易日批量拉取）
支持股票和 ETF 数据拉取，通过 --pool_type 参数切换
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.sources import TushareSource
from data.cache import DataCache
from data.calendar import TradingCalendar
from config import TS_TOKEN


def get_stock_pool():
    """动态导入 stock_pool.py 中的 STOCK_POOL 列表"""
    try:
        from stock_pool import STOCK_POOL
        return STOCK_POOL
    except ImportError:
        print("警告：未找到 stock_pool.py 文件，请先生成股票池。")
        return []


def get_etf_pool():
    """动态导入 etf_pool.py 中的 ETF_POOL 列表"""
    try:
        from etf_pool import ETF_POOL
        return ETF_POOL
    except ImportError:
        print("警告：未找到 etf_pool.py 文件，请先生成 ETF 池。")
        return []


class DataFetcher:
    """数据拉取器（批量优化版，支持股票和 ETF）"""

    def __init__(self, db_path: str = "db/stock.db"):
        self.cache = DataCache(db_path)
        self.source = TushareSource(TS_TOKEN)
        self.calendar = TradingCalendar(db_path)

    # ==================== 股票拉取 ====================

    def fetch_incremental(self, symbols: list = None):
        """增量拉取股票数据"""
        if symbols is None:
            symbols = get_stock_pool()

        if not symbols:
            print("股票池为空，退出。")
            return

        latest_trade_day = self.calendar.latest_trading_day()
        end_date_str = latest_trade_day.strftime("%Y%m%d")
        last_date_global = self.cache.get_global_last_date()

        if last_date_global is None:
            print("本地无股票数据，将执行全量拉取...")
            self.fetch_full(symbols)
            return

        try:
            start_date = self.calendar.next_trading_day(last_date_global).strftime("%Y%m%d")
        except ValueError:
            print("已是最新数据，无需拉取。")
            return

        if start_date > end_date_str:
            print("已是最新数据，无需拉取。")
            return

        trade_dates = self.calendar.get_trading_days(start_date, end_date_str)
        if not trade_dates:
            print("无交易日需要拉取。")
            return

        print(f"增量拉取开始：从 {start_date} 到 {end_date_str}，共 {len(trade_dates)} 个交易日，"
              f"股票池 {len(symbols)} 只")

        total_added = 0
        for date_obj in trade_dates:
            date_str = date_obj.strftime("%Y%m%d")
            date_date = date_obj.strftime("%Y-%m-%d")
            print(f"拉取交易日 {date_str} ...")

            # 日线
            df_daily = self.source.fetch_daily(symbols, date_str, date_str)
            if not df_daily.empty:
                self.cache.save_daily_batch(df_daily)
                total_added += len(df_daily)
                print(f"  日线: {len(df_daily)} 条")

            # 复权因子
            df_factor = self.source.fetch_adjust_factor_by_date(date_str)
            if not df_factor.empty:
                self.cache.save_adjust_factor_batch(df_factor)
                print(f"  复权因子: {len(df_factor)} 条")

            # daily_basic
            df_basic = self.source.fetch_daily_basic(symbols, date_str, date_str)
            if not df_basic.empty:
                self.cache.save_daily_basic_batch(df_basic)
                print(f"  daily_basic: {len(df_basic)} 条")

            self._batch_update_meta(df_daily)

        self.cache.set_global_last_date(latest_trade_day)
        print(f"增量拉取完成，共新增日线记录 {total_added} 条。")

    def fetch_full(self, symbols: list = None, start_date: str = "20100101", end_date: str = None):
        """全量拉取股票数据（按年批量）"""
        if symbols is None:
            symbols = get_stock_pool()

        if end_date is None:
            end_date = datetime.today().strftime("%Y%m%d")

        start_year = int(start_date[:4])
        end_year = int(end_date[:4])

        print(f"全量拉取: {start_date} ~ {end_date}，按年分批，股票池 {len(symbols)} 只")
        total_added = 0

        for year in range(start_year, end_year + 1):
            year_start = max(start_date, f"{year}0101")
            year_end = min(end_date, f"{year}1231")
            print(f"拉取 {year} 年 ({year_start}-{year_end}) ...")

            df_daily = self.source.fetch_daily(symbols, year_start, year_end)
            if df_daily.empty:
                print(f"  {year} 年日线无数据")
            else:
                self.cache.save_daily_batch(df_daily)
                total_added += len(df_daily)
                print(f"  日线: {len(df_daily)} 条")
                self._batch_update_meta(df_daily)

            # 复权因子全量拉取后过滤年份
            df_factor = self.source.fetch_adjust_factor(symbols=symbols)
            if not df_factor.empty:
                df_factor = df_factor[(df_factor["trade_date"] >= year_start) & (df_factor["trade_date"] <= year_end)]
                if not df_factor.empty:
                    self.cache.save_adjust_factor_batch(df_factor)
                    print(f"  复权因子: {len(df_factor)} 条")

            # daily_basic 按年拉取
            df_basic = self.source.fetch_daily_basic(symbols, year_start, year_end)
            if not df_basic.empty:
                self.cache.save_daily_basic_batch(df_basic)
                print(f"  daily_basic: {len(df_basic)} 条")

        self.cache.set_global_last_date(pd.to_datetime(end_date))
        print(f"全量拉取完成，共新增日线记录 {total_added} 条。")

    # ==================== ETF 拉取（新增） ====================

    def fetch_etf_incremental(self, symbols: list = None):
        """增量拉取 ETF 数据"""
        if symbols is None:
            symbols = get_etf_pool()

        if not symbols:
            print("ETF 池为空，退出。")
            return

        latest_trade_day = self.calendar.latest_trading_day()
        end_date_str = latest_trade_day.strftime("%Y%m%d")
        last_date_global = self.cache.get_etf_global_last_date()

        if last_date_global is None:
            print("本地无 ETF 数据，将执行全量拉取...")
            self.fetch_etf_full(symbols)
            return

        try:
            start_date = self.calendar.next_trading_day(last_date_global).strftime("%Y%m%d")
        except ValueError:
            print("ETF 已是最新数据，无需拉取。")
            return

        if start_date > end_date_str:
            print("ETF 已是最新数据，无需拉取。")
            return

        trade_dates = self.calendar.get_trading_days(start_date, end_date_str)
        if not trade_dates:
            print("无交易日需要拉取。")
            return

        print(f"ETF 增量拉取开始：从 {start_date} 到 {end_date_str}，共 {len(trade_dates)} 个交易日，"
              f"ETF 池 {len(symbols)} 只")

        total_added = 0
        for date_obj in trade_dates:
            date_str = date_obj.strftime("%Y%m%d")
            date_date = date_obj.strftime("%Y-%m-%d")
            print(f"拉取 ETF 交易日 {date_str} ...")

            df_etf = self.source.fetch_etf_daily(symbols, date_str, date_str)
            if not df_etf.empty:
                self.cache.save_etf_daily_batch(df_etf)
                total_added += len(df_etf)
                print(f"  ETF 日线: {len(df_etf)} 条")
                self._batch_update_meta(df_etf)

        self.cache.set_etf_global_last_date(latest_trade_day)
        print(f"ETF 增量拉取完成，共新增记录 {total_added} 条。")

    def fetch_etf_full(self, symbols: list = None, start_date: str = "20100101", end_date: str = None):
        """全量拉取 ETF 数据（按年批量）"""
        if symbols is None:
            symbols = get_etf_pool()

        if end_date is None:
            end_date = datetime.today().strftime("%Y%m%d")

        start_year = int(start_date[:4])
        end_year = int(end_date[:4])

        print(f"ETF 全量拉取: {start_date} ~ {end_date}，按年分批，ETF 池 {len(symbols)} 只")
        total_added = 0

        for year in range(start_year, end_year + 1):
            year_start = max(start_date, f"{year}0101")
            year_end = min(end_date, f"{year}1231")
            print(f"拉取 ETF {year} 年 ({year_start}-{year_end}) ...")

            df_etf = self.source.fetch_etf_daily(symbols, year_start, year_end)
            if df_etf.empty:
                print(f"  {year} 年 ETF 日线无数据")
            else:
                self.cache.save_etf_daily_batch(df_etf)
                total_added += len(df_etf)
                print(f"  ETF 日线: {len(df_etf)} 条")
                self._batch_update_meta(df_etf)

        self.cache.set_etf_global_last_date(pd.to_datetime(end_date))
        print(f"ETF 全量拉取完成，共新增记录 {total_added} 条。")

    # ==================== 通用辅助 ====================

    def _batch_update_meta(self, df_daily: pd.DataFrame):
        """从日线数据中提取每只证券的最新交易日期，批量更新 meta 表"""
        if df_daily.empty:
            return
        meta_update = df_daily.groupby("ts_code")["trade_date"].max().reset_index()
        for _, row in meta_update.iterrows():
            last_date_str = pd.Timestamp(row["trade_date"]).strftime("%Y-%m-%d")
            self.cache.update_meta(row["ts_code"], last_date_str, None)


def main():
    parser = argparse.ArgumentParser(description="A股数据拉取工具（支持股票和ETF）")
    parser.add_argument("--mode", choices=["incremental", "full"], default="incremental",
                        help="拉取模式：incremental(增量) 或 full(全量)")
    parser.add_argument("--pool_type", choices=["stock", "etf"], default="stock",
                        help="拉取类型：stock(股票) 或 etf(ETF)")
    parser.add_argument("--symbols", type=str, default=None,
                        help="指定代码，逗号分隔，例如 000001.SZ,600000.SH 或 510050.SH,159915.SZ")
    parser.add_argument("--start", type=str, default="20100101",
                        help="全量模式下的开始日期 (YYYYMMDD)")
    parser.add_argument("--end", type=str, default=None,
                        help="全量模式下的结束日期 (YYYYMMDD)")

    args = parser.parse_args()

    # 根据 pool_type 确定代码列表
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",")]
    else:
        if args.pool_type == "etf":
            symbols = get_etf_pool()
        else:
            symbols = get_stock_pool()

    if not symbols:
        print(f"未指定代码，且对应的池文件为空，退出。")
        return

    fetcher = DataFetcher()

    if args.pool_type == "etf":
        if args.mode == "incremental":
            fetcher.fetch_etf_incremental(symbols)
        else:
            fetcher.fetch_etf_full(symbols, start_date=args.start, end_date=args.end)
    else:
        if args.mode == "incremental":
            fetcher.fetch_incremental(symbols)
        else:
            fetcher.fetch_full(symbols, start_date=args.start, end_date=args.end)


if __name__ == "__main__":
    main()