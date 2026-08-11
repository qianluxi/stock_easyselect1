"""
数据拉取调度器（优化版：支持时间分段、重试与冷却）
支持股票和 ETF 数据拉取，通过 --pool_type 和 --time_split 参数控制
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime
from dateutil.relativedelta import relativedelta  # 需要安装：pip install python-dateutil
import pandas as pd
from db.database import SQLiteDB

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.sources import TushareSource
from data.cache import DataCache
from data.calendar import TradingCalendar
from config import TS_TOKEN
import time


def get_stock_pool():
    try:
        from stock_pool import STOCK_POOL
        return STOCK_POOL
    except ImportError:
        print("警告：未找到 stock_pool.py 文件，请先生成股票池。")
        return []


def get_etf_pool():
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
        """增量拉取股票数据（按日拉取全市场，避免代码拼接导致的截断）"""
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
            self.fetch_full_all(symbols)  # 调用完善的全量拉取
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
            print(f"拉取交易日 {date_str} ...")

            # 日线：按日获取全市场，再过滤池子
            df_daily = self.source.fetch_daily_by_date(date_str, symbols)
            if not df_daily.empty:
                self.cache.save_daily_batch(df_daily)
                total_added += len(df_daily)
                print(f"  日线: {len(df_daily)} 条")

            # 复权因子：按日获取全市场
            df_factor = self.source.fetch_adjust_factor_by_date(date_str, symbols)
            if not df_factor.empty:
                self.cache.save_adjust_factor_batch(df_factor)
                print(f"  复权因子: {len(df_factor)} 条")

            # 每日基本面：按日获取全市场
            df_basic = self.source.fetch_daily_basic_by_date(date_str, symbols)
            if not df_basic.empty:
                self.cache.save_daily_basic_batch(df_basic)
                print(f"  daily_basic: {len(df_basic)} 条")

            self._batch_update_meta(df_daily)

        self.cache.set_global_last_date(latest_trade_day)
        print(f"增量拉取完成，共新增日线记录 {total_added} 条。")

    def fetch_full(self, symbols: list = None, start_date: str = "20100101", end_date: str = None,
                   time_split: str = "year"):
        """
        全量拉取股票数据（支持按年/季度/月分段）
        time_split: 'year', 'quarter', 'month'，默认 'year' 保持向后兼容
        """
        if symbols is None:
            symbols = get_stock_pool()

        if end_date is None:
            end_date = datetime.today().strftime("%Y%m%d")

        print(f"全量拉取: {start_date} ~ {end_date}，股票池 {len(symbols)} 只，时间分段: {time_split}")
        total_added = 0

        # 生成时间区间列表
        chunks = self._generate_time_chunks(start_date, end_date, time_split)

        for chunk_start, chunk_end in chunks:
            print(f"拉取时间段 {chunk_start} ~ {chunk_end} ...")

            # 日线
            df_daily = self.source.fetch_daily(symbols, chunk_start, chunk_end)
            if df_daily.empty:
                print(f"  该时间段日线无数据")
            else:
                stocks_in_response = df_daily['ts_code'].nunique()
                records_in_response = len(df_daily)
                print(f"  [调试] 请求返回 {records_in_response} 条记录，涉及 {stocks_in_response} 只股票")

                missing_stocks = set(symbols) - set(df_daily['ts_code'].unique())
                if missing_stocks:
                    print(f"  [调试] 请求返回中缺失 {len(missing_stocks)} 只股票，前10只: {list(missing_stocks)[:10]}")

                self.cache.save_daily_batch(df_daily)
                total_added += records_in_response
                print(f"  日线: {records_in_response} 条")
                self._batch_update_meta(df_daily)

                # 数据库验证
                db = SQLiteDB(self.db_path)
                db.connect()
                df_check = db.query(
                    "SELECT COUNT(DISTINCT ts_code) as cnt FROM daily_raw WHERE trade_date >= ? AND trade_date <= ?",
                    (chunk_start, chunk_end)
                )
                saved_stocks = df_check.iloc[0]['cnt'] if not df_check.empty else 0
                print(f"  [调试] 保存后该时段数据库中股票数: {saved_stocks}")
                db.close()

            # 复权因子（针对该时段过滤）
            df_factor = self.source.fetch_adjust_factor(symbols=symbols)
            if not df_factor.empty:
                df_factor = df_factor[(df_factor["trade_date"] >= chunk_start) & (df_factor["trade_date"] <= chunk_end)]
                if not df_factor.empty:
                    self.cache.save_adjust_factor_batch(df_factor)
                    print(f"  复权因子: {len(df_factor)} 条")
                else:
                    print(f"  复权因子: 该时段无数据")
            else:
                print(f"  复权因子: 请求返回空")

            # daily_basic
            df_basic = self.source.fetch_daily_basic(symbols, chunk_start, chunk_end)
            if not df_basic.empty:
                self.cache.save_daily_basic_batch(df_basic)
                print(f"  daily_basic: {len(df_basic)} 条")
            else:
                print(f"  daily_basic: 无数据")

        self.cache.set_global_last_date(pd.to_datetime(end_date))
        print(f"全量拉取完成，共新增日线记录 {total_added} 条。")

    def fetch_full_by_dates(self, symbols: list = None, start_date: str = "20200101", end_date: str = None):
        """
        全量拉取（按交易日逐个进行，彻底避免记录截断）
        """
        if symbols is None:
            symbols = get_stock_pool()
        if end_date is None:
            end_date = datetime.today().strftime("%Y%m%d")

        trade_dates = self.calendar.get_trading_days(start_date, end_date)
        print(f"按日全量拉取: {start_date} ~ {end_date}，共 {len(trade_dates)} 个交易日，股票池 {len(symbols)} 只")
        total_added = 0

        for idx, date_obj in enumerate(trade_dates, 1):
            date_str = date_obj.strftime("%Y%m%d")
            if idx % 20 == 0 or idx == 1:   # 每20天打印一次进度
                print(f"  进度: {idx}/{len(trade_dates)} 交易日 {date_str}")
            df_daily = self.source.fetch_daily_by_date(date_str, symbols)
            if not df_daily.empty:
                self.cache.save_daily_batch(df_daily)
                total_added += len(df_daily)
                self._batch_update_meta(df_daily)
            # 每日请求后的间隔由 TushareSource 内部的 SLEEP_RANGE 控制（已在 _clean_daily_data 或 batch_request 中处理，这里可额外加轻微延迟）
            time.sleep(0.2)   # 额外微小延迟，避免极快连续请求

        self.cache.set_global_last_date(pd.to_datetime(end_date))
        print(f"按日全量拉取完成，共新增日线记录 {total_added} 条。")

    def _generate_time_chunks(self, start_date: str, end_date: str, split: str):
        """
        生成 (chunk_start, chunk_end) 列表，格式均为 YYYYMMDD
        split: 'year', 'quarter', 'month'
        """
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)
        chunks = []

        if split == 'year':
            for year in range(start_dt.year, end_dt.year + 1):
                y_start = max(start_date, f"{year}0101")
                y_end = min(end_date, f"{year}1231")
                chunks.append((y_start, y_end))
        elif split == 'quarter':
            current = start_dt
            while current <= end_dt:
                quarter_start = current
                # 计算本季度结束日期
                quarter_end = (quarter_start + pd.DateOffset(months=3)) - pd.DateOffset(days=1)
                if quarter_end > end_dt:
                    quarter_end = end_dt
                chunks.append((quarter_start.strftime("%Y%m%d"), quarter_end.strftime("%Y%m%d")))
                current = quarter_end + pd.DateOffset(days=1)
        elif split == 'month':
            current = start_dt
            while current <= end_dt:
                month_start = current
                # 本月最后一天
                month_end = (month_start + pd.DateOffset(months=1)) - pd.DateOffset(days=1)
                if month_end > end_dt:
                    month_end = end_dt
                chunks.append((month_start.strftime("%Y%m%d"), month_end.strftime("%Y%m%d")))
                current = month_end + pd.DateOffset(days=1)
        else:
            # 默认按年
            return self._generate_time_chunks(start_date, end_date, 'year')
        return chunks

    def fetch_repair(self, symbols: list = None, start_date: str = "20220101"):
        """补全模式：按年检查缺失，仅拉取缺失年份的数据（保留原有逻辑）"""
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
            year_start_db = f"{year}-01-01"
            year_end_db = f"{year}-12-31"

            sql = """
                SELECT DISTINCT ts_code FROM daily_raw
                WHERE trade_date >= ? AND trade_date <= ?
            """
            df_exist = db.query(sql, (year_start_db, year_end_db))
            exist_codes = set(df_exist['ts_code'].tolist()) if not df_exist.empty else set()

            need_repair = [s for s in symbols if s not in exist_codes]
            if not need_repair:
                print(f"{year} 年没有缺失，跳过。")
                continue

            print(f"{year} 年缺失数据股票数: {len(need_repair)}，开始补拉...")
            year_start_fetch = f"{year}0101"
            year_end_fetch = f"{year}1231"
            df_daily = self.source.fetch_daily(need_repair, year_start_fetch, year_end_fetch)
            if not df_daily.empty:
                self.cache.save_daily_batch(df_daily)
                total_added += len(df_daily)
                print(f"  补全日线: {len(df_daily)} 条")
                self._batch_update_meta(df_daily)
            else:
                print(f"  该年无数据返回")

            df_factor = self.source.fetch_adjust_factor(symbols=need_repair)
            if not df_factor.empty:
                df_factor = df_factor[(df_factor['trade_date'] >= year_start_db) & (df_factor['trade_date'] <= year_end_db)]
                if not df_factor.empty:
                    self.cache.save_adjust_factor_batch(df_factor)
                    print(f"  补全复权因子: {len(df_factor)} 条")

        db.close()
        print(f"补全完成，共新增日线记录 {total_added} 条。")

    # ==================== ETF 拉取 ====================
    def fetch_etf_incremental(self, symbols: list = None):
        """增量拉取 ETF 数据（按交易日，避免逐只请求导致过慢）"""
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

        # 探测按日拉取是否可用（fund_daily trade_date 参数）
        probe = self.source.fetch_etf_daily_by_date(
            trade_dates[0].strftime("%Y%m%d"), symbols[:10]
        )
        if probe.empty:
            print("ETF 按交易日拉取不可用，请先执行全量拉取（--mode full --pool_type etf）。")
            return

        total_added = 0
        for idx, date_obj in enumerate(trade_dates, 1):
            date_str = date_obj.strftime("%Y%m%d")
            if idx % 20 == 0 or idx == 1:
                print(f"  进度: {idx}/{len(trade_dates)} 交易日 {date_str}")
            df_etf = self.source.fetch_etf_daily_by_date(date_str, symbols)
            if not df_etf.empty:
                self.cache.save_etf_daily_batch(df_etf)
                total_added += len(df_etf)
                self._batch_update_meta(df_etf)
            time.sleep(0.3)

        self.cache.set_etf_global_last_date(latest_trade_day)
        print(f"ETF 增量拉取完成，共新增记录 {total_added} 条。")

    def fetch_etf_full(self, symbols: list = None, start_date: str = "20100101", end_date: str = None):
        """全量拉取 ETF 数据（按交易日拉取，推荐方式）"""
        if symbols is None:
            symbols = get_etf_pool()
        if end_date is None:
            end_date = datetime.today().strftime("%Y%m%d")

        trade_dates = self.calendar.get_trading_days(start_date, end_date)
        if not trade_dates:
            print("无交易日需要拉取。")
            return

        # 探测按日拉取是否可用（fund_daily trade_date 参数）
        probe = self.source.fetch_etf_daily_by_date(
            trade_dates[0].strftime("%Y%m%d"), symbols[:10]
        )
        if probe.empty:
            print("按交易日拉取不可用（fund_daily 不支持 trade_date 参数或权限不足），回退为逐只按年拉取 ...")
            self._fetch_etf_full_legacy(symbols, start_date, end_date)
            return

        print(f"ETF 全量拉取: {start_date} ~ {end_date}，按交易日，ETF 池 {len(symbols)} 只，"
              f"共 {len(trade_dates)} 个交易日")
        total_added = 0

        for idx, date_obj in enumerate(trade_dates, 1):
            date_str = date_obj.strftime("%Y%m%d")
            if idx % 20 == 0 or idx == 1:
                print(f"  进度: {idx}/{len(trade_dates)} 交易日 {date_str}")
            df_etf = self.source.fetch_etf_daily_by_date(date_str, symbols)
            if not df_etf.empty:
                self.cache.save_etf_daily_batch(df_etf)
                total_added += len(df_etf)
                self._batch_update_meta(df_etf)
            time.sleep(0.3)

        self.cache.set_etf_global_last_date(pd.to_datetime(end_date))
        print(f"ETF 全量拉取完成，共新增记录 {total_added} 条。")

    def _fetch_etf_full_legacy(self, symbols: list = None, start_date: str = "20100101", end_date: str = None):
        """全量拉取 ETF 数据（旧版：逐只按年拉取，作为按日拉取不可用时的回退）"""
        if symbols is None:
            symbols = get_etf_pool()
        if end_date is None:
            end_date = datetime.today().strftime("%Y%m%d")

        start_year = int(start_date[:4])
        end_year = int(end_date[:4])
        print(f"ETF 全量拉取（逐只按年）: {start_date} ~ {end_date}，ETF 池 {len(symbols)} 只")
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
        if df_daily.empty:
            return
        meta_update = df_daily.groupby("ts_code")["trade_date"].max().reset_index()
        for _, row in meta_update.iterrows():
            last_date_str = pd.Timestamp(row["trade_date"]).strftime("%Y-%m-%d")
            self.cache.update_meta(row["ts_code"], last_date_str, None)


    def fetch_full_daily_basic_by_dates(self, symbols=None, start_date='20200101', end_date=None):
        if symbols is None:
            symbols = get_stock_pool()
        if end_date is None:
            end_date = datetime.today().strftime("%Y%m%d")
        trade_dates = self.calendar.get_trading_days(start_date, end_date)
        print(f"按日补全 daily_basic: {start_date}~{end_date}，共 {len(trade_dates)} 交易日")
        total_added = 0
        for idx, date_obj in enumerate(trade_dates, 1):
            date_str = date_obj.strftime("%Y%m%d")
            if idx % 20 == 0:
                print(f"  进度: {idx}/{len(trade_dates)} {date_str}")
            df_basic = self.source.fetch_daily_basic_by_date(date_str, symbols)
            if not df_basic.empty:
                self.cache.save_daily_basic_batch(df_basic)
                total_added += len(df_basic)
            time.sleep(0.3)  # 适当频率
        print(f"daily_basic 补全完成，新增 {total_added} 条")

    def fetch_full_all(self, symbols=None, start_date='20200101', end_date=None):
        """
        全量拉取（按交易日，一次性获取 daily_raw、daily_basic、adjust_factor）
        """
        if symbols is None:
            symbols = get_stock_pool()
        if end_date is None:
            end_date = datetime.today().strftime("%Y%m%d")

        trade_dates = self.calendar.get_trading_days(start_date, end_date)
        print(f"全量拉取（日线+基本面+复权因子）: {start_date}~{end_date}, 共 {len(trade_dates)} 天, 股票 {len(symbols)} 只")
        
        total_daily = total_basic = total_adj = 0
        for idx, date_obj in enumerate(trade_dates, 1):
            date_str = date_obj.strftime("%Y%m%d")
            if idx % 20 == 0 or idx == 1:
                print(f"进度: {idx}/{len(trade_dates)} {date_str}")
            
            # 拉取日线
            df_daily = self.source.fetch_daily_by_date(date_str, symbols)
            if not df_daily.empty:
                self.cache.save_daily_batch(df_daily)
                total_daily += len(df_daily)
                self._batch_update_meta(df_daily)
            
            # 拉取基本面
            df_basic = self.source.fetch_daily_basic_by_date(date_str, symbols)
            if not df_basic.empty:
                self.cache.save_daily_basic_batch(df_basic)
                total_basic += len(df_basic)
            
            # 拉取复权因子（每天可能只有少量除权股，但也要拉）
            df_adj = self.source.fetch_adjust_factor_by_date(date_str, symbols)
            if not df_adj.empty:
                self.cache.save_adjust_factor_batch(df_adj)
                total_adj += len(df_adj)
            
            time.sleep(0.3)  # 控制频率

        self.cache.set_global_last_date(pd.to_datetime(end_date))
        print(f"完成：日线 {total_daily} 条, 基本面 {total_basic} 条, 复权因子 {total_adj} 条")


def main():
    parser = argparse.ArgumentParser(description="A股数据拉取工具（支持股票和ETF）")
    parser.add_argument("--mode", choices=["incremental", "full", "repair"], default="incremental",
                        help="拉取模式")
    parser.add_argument("--pool_type", choices=["stock", "etf"], default="stock",
                        help="拉取类型")
    parser.add_argument("--symbols", type=str, default=None,
                        help="指定代码，逗号分隔")
    parser.add_argument("--start", type=str, default="20100101",
                        help="全量/补全模式下的开始日期 (YYYYMMDD)")
    parser.add_argument("--end", type=str, default=None,
                        help="全量模式下的结束日期 (YYYYMMDD)")
    parser.add_argument("--time_split", choices=["year", "quarter", "month"], default="year",
                        help="全量拉取时的时间分段粒度，降低单次请求数据量 (默认 year，仅在 --legacy 时有效)")
    parser.add_argument("--legacy", action="store_true", help="全量拉取使用旧的分段方式（按年/季度/月）")

    args = parser.parse_args()

    # 确定股票/ETF 代码列表
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

    # ========================= ETF 分支 =========================
    if args.pool_type == "etf":
        if args.mode == "incremental":
            fetcher.fetch_etf_incremental(symbols)
        elif args.mode == "full":
            fetcher.fetch_etf_full(symbols, start_date=args.start, end_date=args.end)
        else:
            print("错误：ETF 暂不支持 repair 模式，请使用 stock 池或手动执行。")
            return
        return  # ETF 分支结束

    # ========================= 股票分支 =========================
    if args.mode == "incremental":
        fetcher.fetch_incremental(symbols)

    elif args.mode == "full":
        if args.legacy:
            # 旧版：按年/季度/月分段拉取（仅日线，不包括 basic 和 adj_factor 的完整保护）
            fetcher.fetch_full(symbols, start_date=args.start, end_date=args.end,
                               time_split=args.time_split)
        else:
            # 新版默认：按交易日拉取，一次性获取 daily_raw、daily_basic、adjust_factor
            # 彻底解决数据截断与缺失
            fetcher.fetch_full_all(symbols, start_date=args.start, end_date=args.end)

    elif args.mode == "repair":
        fetcher.fetch_repair(symbols, start_date=args.start)

    else:
        print("未知模式。")


if __name__ == "__main__":
    main()
