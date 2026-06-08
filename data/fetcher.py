"""
数据拉取调度器（优化版：按交易日批量拉取）
支持股票和 ETF 数据拉取，通过 --pool_type 参数切换
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime
import pandas as pd
from db.database import SQLiteDB

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
        self.db_path = db_path
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
        """
        全量拉取股票数据（按年批量）
        包含详细的调试日志，用于诊断数据缺失原因。
        """
        if symbols is None:
            symbols = get_stock_pool()

        if end_date is None:
            end_date = datetime.today().strftime("%Y%m%d")

        start_year = int(start_date[:4])
        end_year = int(end_date[:4])

        print(f"全量拉取: {start_date} ~ {end_date}，按年分批，股票池 {len(symbols)} 只")
        total_added = 0

        # 导入 SQLiteDB 用于调试查询
        from db.database import SQLiteDB

        for year in range(start_year, end_year + 1):
            year_start = max(start_date, f"{year}0101")
            year_end = min(end_date, f"{year}1231")
            print(f"拉取 {year} 年 ({year_start}-{year_end}) ...")

            # ---------- 1. 拉取日线 ----------
            df_daily = self.source.fetch_daily(symbols, year_start, year_end)
            if df_daily.empty:
                print(f"  {year} 年日线无数据")
            else:
                # 记录本次拉取到的股票和记录数
                stocks_in_response = df_daily['ts_code'].nunique()
                records_in_response = len(df_daily)
                print(f"  [调试] 请求返回 {records_in_response} 条记录，涉及 {stocks_in_response} 只股票")

                # 找出池子中有但响应中缺失的股票
                missing_stocks = set(symbols) - set(df_daily['ts_code'].unique())
                if missing_stocks:
                    print(f"  [调试] 请求返回中缺失 {len(missing_stocks)} 只股票，前10只: {list(missing_stocks)[:10]}")

                # 保存到数据库
                self.cache.save_daily_batch(df_daily)
                total_added += records_in_response
                print(f"  日线: {records_in_response} 条")
                self._batch_update_meta(df_daily)

                # ---------- 数据库验证 ----------
                db = SQLiteDB(self.db_path)
                db.connect()
                # 查询该年范围内已有数据的股票数
                df_check = db.query(
                    "SELECT COUNT(DISTINCT ts_code) as cnt FROM daily_raw WHERE trade_date >= ? AND trade_date <= ?",
                    (year_start, year_end)
                )
                saved_stocks = df_check.iloc[0]['cnt'] if not df_check.empty else 0
                print(f"  [调试] 保存后该年数据库中股票数: {saved_stocks}")
                db.close()

            # ---------- 2. 复权因子 ----------
            df_factor = self.source.fetch_adjust_factor(symbols=symbols)
            if not df_factor.empty:
                # 按年份过滤
                df_factor = df_factor[(df_factor["trade_date"] >= year_start) & (df_factor["trade_date"] <= year_end)]
                if not df_factor.empty:
                    self.cache.save_adjust_factor_batch(df_factor)
                    print(f"  复权因子: {len(df_factor)} 条")
                else:
                    print(f"  复权因子: 该年无数据")
            else:
                print(f"  复权因子: 请求返回空")

            # ---------- 3. daily_basic ----------
            df_basic = self.source.fetch_daily_basic(symbols, year_start, year_end)
            if not df_basic.empty:
                self.cache.save_daily_basic_batch(df_basic)
                print(f"  daily_basic: {len(df_basic)} 条")
            else:
                print(f"  daily_basic: 无数据")

        self.cache.set_global_last_date(pd.to_datetime(end_date))
        print(f"全量拉取完成，共新增日线记录 {total_added} 条。")

    def fetch_repair(self, symbols: list = None, start_date: str = "20220101"):
        """
        补全模式：按年检查每只股票在数据库中的缺失情况，仅拉取缺失年份的数据
        """
        if symbols is None:
            symbols = get_stock_pool()
        if not symbols:
            print("股票池为空，退出。")
            return

        end_date = self.calendar.latest_trading_day().strftime("%Y%m%d")
        start_year = int(start_date[:4])
        end_year = int(end_date[:4])

        print(f"补全模式：检查 {start_year}~{end_year} 年数据，股票池 {len(symbols)} 只")
        total_added = 0

        db = SQLiteDB(self.db_path)
        db.connect()

        for year in range(start_year, end_year + 1):
            # 数据库中的日期格式为 YYYY-MM-DD
            year_start_db = f"{year}-01-01"
            year_end_db = f"{year}-12-31"

            # 查询该年内已经有记录的股票
            sql = """
                SELECT DISTINCT ts_code FROM daily_raw
                WHERE trade_date >= ? AND trade_date <= ?
            """
            df_exist = db.query(sql, (year_start_db, year_end_db))
            exist_codes = set(df_exist['ts_code'].tolist()) if not df_exist.empty else set()

            # 需要补拉的股票：池子里有，但该年没记录的
            need_repair = [s for s in symbols if s not in exist_codes]
            if not need_repair:
                print(f"{year} 年没有缺失，跳过。")
                continue

            print(f"{year} 年缺失数据股票数: {len(need_repair)}，开始补拉...")
            # fetch_daily 仍使用 YYYYMMDD 格式
            year_start_fetch = f"{year}0101"
            year_end_fetch = f"{year}1231"
            df_daily = self.source.fetch_daily(need_repair, year_start_fetch, year_end_fetch)
            if not df_daily.empty:
                self.cache.save_daily_batch(df_daily)
                total_added += len(df_daily)
                print(f"  补全日线: {len(df_daily)} 条")
                self._batch_update_meta(df_daily)
            else:
                print(f"  该年无数据返回（可能不存在或权限不足）")

            # 可选：补全复权因子（若需要）
            df_factor = self.source.fetch_adjust_factor(symbols=need_repair)
            if not df_factor.empty:
                # 过滤出该年范围内的因子
                df_factor = df_factor[(df_factor['trade_date'] >= year_start_db) & (df_factor['trade_date'] <= year_end_db)]
                if not df_factor.empty:
                    self.cache.save_adjust_factor_batch(df_factor)
                    print(f"  补全复权因子: {len(df_factor)} 条")

        db.close()
        print(f"补全完成，共新增日线记录 {total_added} 条。")

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
    parser.add_argument("--mode", choices=["incremental", "full", "repair"], default="incremental",
                        help="拉取模式：incremental(增量)、full(全量)、repair(补全缺失)")
    parser.add_argument("--pool_type", choices=["stock", "etf"], default="stock",
                        help="拉取类型：stock(股票) 或 etf(ETF)")
    parser.add_argument("--symbols", type=str, default=None,
                        help="指定代码，逗号分隔")
    parser.add_argument("--start", type=str, default="20100101",
                        help="全量/补全模式下的开始日期 (YYYYMMDD)")
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
        print("未指定代码，且对应的池文件为空，退出。")
        return

    fetcher = DataFetcher()

    if args.pool_type == "etf":
        if args.mode == "incremental":
            fetcher.fetch_etf_incremental(symbols)
        elif args.mode == "full":
            fetcher.fetch_etf_full(symbols, start_date=args.start, end_date=args.end)
        else:  # repair mode
            print("错误：ETF 暂不支持 repair 模式，请使用 stock 池或手动执行全量拉取。")
            return
    else:  # stock pool
        if args.mode == "incremental":
            fetcher.fetch_incremental(symbols)
        elif args.mode == "full":
            fetcher.fetch_full(symbols, start_date=args.start, end_date=args.end)
        elif args.mode == "repair":
            fetcher.fetch_repair(symbols, start_date=args.start)
        else:
            print("未知模式。")
            return

if __name__ == "__main__":
    main()