"""
数据拉取调度器
负责从 Tushare 拉取股票池数据，支持增量更新
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd

# 添加项目根目录到 sys.path，以便导入 stock_pool
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


class DataFetcher:
    """数据拉取器"""

    def __init__(self, db_path: str = "db/stock.db"):
        self.cache = DataCache(db_path)
        self.source = TushareSource(TS_TOKEN)
        self.calendar = TradingCalendar(db_path)

    def fetch_incremental(self, symbols: list = None):
        """
        增量拉取：只拉取每只股票本地缓存之后的新数据
        """
        if symbols is None:
            symbols = get_stock_pool()

        if not symbols:
            print("股票池为空，退出。")
            return

        latest_trading_day = self.calendar.latest_trading_day()
        end_date = latest_trading_day.strftime("%Y%m%d")
        latest_date_obj = latest_trading_day.date()  # 用于日期比较

        print(f"增量拉取开始，目标结束日期: {end_date}，股票数量: {len(symbols)}")

        for i, sym in enumerate(symbols, 1):
            print(f"[{i}/{len(symbols)}] 处理 {sym}...")

            last_date = self.cache.get_last_update_date(sym)
            if last_date:
                last_date_obj = pd.to_datetime(last_date).date()
                # 如果缓存的最新日期已经等于或晚于最新交易日，则无需拉取
                if last_date_obj >= latest_date_obj:
                    print(f"  {sym} 已是最新，跳过")
                    continue
                # 尝试获取下一个交易日，若不存在则跳过
                try:
                    start_date = self.calendar.next_trading_day(last_date).strftime("%Y%m%d")
                except ValueError:
                    print(f"  {sym} 已是最新，跳过 (无后续交易日)")
                    continue
            else:
                # 无缓存，默认从 2010-01-01 开始
                start_date = "20100101"

            # 再次检查开始日期是否晚于结束日期（理论上不会，但保留防御）
            if start_date > end_date:
                print(f"  {sym} 已是最新，跳过")
                continue

            df = self.source.fetch_daily([sym], start_date, end_date)
            if df.empty:
                print(f"  {sym} 无新数据")
                continue

            # 保存到缓存
            self.cache.save_daily_batch(df)
            # 同步拉取复权因子
            self._fetch_and_save_adjust_factor(sym, start_date, end_date)
            # 同步拉取总市值、换手率等
            self._fetch_and_save_daily_basic(sym, start_date, end_date)

            # --- 修复日期提取逻辑 ---
            trade_dates = pd.to_datetime(df["trade_date"], errors="coerce")
            max_date_ts = trade_dates.max()
            if pd.notna(max_date_ts):
                max_date_str = max_date_ts.strftime("%Y-%m-%d")
            else:
                max_date_str = "未知"

            self.cache.update_meta(sym, max_date_str, len(df))
            print(f"  {sym} 新增 {len(df)} 条记录，最新日期 {max_date_str}")

    def fetch_full(self, symbols: list = None, start_date: str = "20100101", end_date: str = None):
        """
        全量拉取：拉取指定日期范围内的全部数据，覆盖已有数据
        """
        if symbols is None:
            symbols = get_stock_pool()

        if end_date is None:
            end_date = datetime.today().strftime("%Y%m%d")

        print(f"全量拉取: {start_date} ~ {end_date}, 股票数量: {len(symbols)}")

        for i, sym in enumerate(symbols, 1):
            print(f"[{i}/{len(symbols)}] 处理 {sym}...")
            df = self.source.fetch_daily([sym], start_date, end_date)
            if df.empty:
                print(f"  {sym} 无数据")
                continue

            self.cache.save_daily_batch(df)
            # 新增：同步拉取复权因子
            self._fetch_and_save_adjust_factor(sym, start_date, end_date)
            self._fetch_and_save_daily_basic(sym, start_date, end_date)   # 新增总市值换手率等

            # --- 修复日期提取逻辑 ---
            trade_dates = pd.to_datetime(df["trade_date"], errors="coerce")
            max_date_ts = trade_dates.max()
            if pd.notna(max_date_ts):
                max_date_str = max_date_ts.strftime("%Y-%m-%d")
            else:
                max_date_str = "未知"

            self.cache.update_meta(sym, max_date_str, len(df))
            print(f"  {sym} 共 {len(df)} 条记录，最新日期 {max_date_str}")

    def _fetch_and_save_adjust_factor(self, symbol: str, start_date: str, end_date: str):
        """
        拉取单只股票的复权因子并存入缓存
        """
        df_factor = self.source.fetch_adjust_factor(trade_date=None, symbols=[symbol])
        if df_factor.empty:
            return

        # 过滤出日期范围内的数据
        df_factor["trade_date_raw"] = pd.to_datetime(df_factor["trade_date"], format="%Y%m%d")
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)
        mask = (df_factor["trade_date_raw"] >= start_dt) & (df_factor["trade_date_raw"] <= end_dt)
        df_filtered = df_factor.loc[mask].copy()
        if df_filtered.empty:
            return

        df_filtered["trade_date"] = df_filtered["trade_date_raw"].dt.strftime("%Y-%m-%d")
        self.cache.save_adjust_factor_batch(df_filtered[["ts_code", "trade_date", "adj_factor"]])

    #拉取单只股票的总市值换手率等数据并存储
    def _fetch_and_save_daily_basic(self, symbol: str, start_date: str, end_date: str):
        """拉取单只股票的 daily_basic 数据并存储"""
        df_basic = self.source.fetch_daily_basic([symbol], start_date, end_date)
        if df_basic.empty:
            print(f"  {symbol} daily_basic 无数据")
            return
        self.cache.save_daily_basic_batch(df_basic)
        print(f"  {symbol} daily_basic 新增 {len(df_basic)} 条记录")


def main():
    parser = argparse.ArgumentParser(description="A股数据拉取工具")
    parser.add_argument("--mode", choices=["incremental", "full"], default="incremental",
                        help="拉取模式：incremental(增量) 或 full(全量)")
    parser.add_argument("--symbols", type=str, default=None,
                        help="指定股票代码，逗号分隔，例如 000001.SZ,600000.SH")
    parser.add_argument("--start", type=str, default="20100101",
                        help="全量模式下的开始日期 (YYYYMMDD)")
    parser.add_argument("--end", type=str, default=None,
                        help="全量模式下的结束日期 (YYYYMMDD)")

    args = parser.parse_args()

    # 处理股票列表
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",")]
    else:
        symbols = get_stock_pool()

    if not symbols:
        print("未指定股票池，且 stock_pool.py 为空，退出。")
        return

    fetcher = DataFetcher()

    if args.mode == "incremental":
        fetcher.fetch_incremental(symbols)
    else:
        fetcher.fetch_full(symbols, start_date=args.start, end_date=args.end)


if __name__ == "__main__":
    main()